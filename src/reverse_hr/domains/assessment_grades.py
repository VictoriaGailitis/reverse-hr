"""Reviewed calibration policies, session aggregation and independent grade/retry limits."""

from datetime import UTC, datetime, timedelta
from fractions import Fraction
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract, Grade
from reverse_hr.domains.assessment import AssessmentBase, ContentRevision
from reverse_hr.domains.assessment_sessions import (
    PlanVersion,
    PracticalSession,
    StageState,
    emit,
    subject_lock,
    utc,
)
from reverse_hr.grade_access import StageScore
from reverse_hr.test_suites import digest


class Rules(Contract):
    required_llm_model: str | None = Field(default=None, min_length=1, max_length=200)
    required_llm_prompt_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    weights: dict[str, Annotated[int, Field(strict=True, ge=1, le=100)]] = Field(
        min_length=1, max_length=20
    )
    minimums: dict[str, Annotated[int, Field(strict=True, ge=0, le=100)]] = Field(
        default_factory=dict, max_length=20
    )
    pass_score: int = Field(strict=True, ge=1, le=100)
    retry_seconds: int = Field(strict=True, ge=0, le=31536000)
    grade_change_seconds: int = Field(default=7776000, strict=True, ge=0, le=31536000)
    minimum_validation_cases: int = Field(default=20, strict=True, ge=20, le=2000)
    minimum_accuracy_percent: int = Field(default=80, strict=True, ge=80, le=100)

    @model_validator(mode="after")
    def coherent(self):
        if (self.required_llm_model is None) != (self.required_llm_prompt_digest is None):
            raise ValueError("Model and prompt policy must be specified together")
        if (
            sum(self.weights.values()) != 100
            or any(type(v) is not int or not 1 <= v <= 100 for v in self.weights.values())
            or not set(self.minimums) <= set(self.weights)
            or any(type(v) is not int or not 0 <= v <= 100 for v in self.minimums.values())
        ):
            raise ValueError("Invalid competency weights or minimums")
        return self


class ExpertLabel(Contract):
    expert_id: UUID
    passed: bool = Field(strict=True)


class CalibrationCase(Contract):
    case_id: UUID
    scores: dict[str, Annotated[int, Field(strict=True, ge=0, le=100)]] = Field(
        min_length=1, max_length=20
    )
    labels: list[ExpertLabel] = Field(min_length=2, max_length=5)
    holdout: Literal[True]

    @model_validator(mode="after")
    def coherent(self):
        if (
            len({label.expert_id for label in self.labels}) != len(self.labels)
            or len({label.passed for label in self.labels}) != 1
            or any(type(v) is not int or not 0 <= v <= 100 for v in self.scores.values())
        ):
            raise ValueError("Independent agreed expert labels and bounded scores required")
        return self


class CalibrationData(Contract):
    source_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    scoring_version: Literal["competency-weighted-v1"]
    cases: list[CalibrationCase] = Field(min_length=20, max_length=2000)
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")

    @model_validator(mode="after")
    def coherent(self):
        if len({label.expert_id for c in self.cases for label in c.labels}) > 16:
            raise ValueError("Calibration supports at most 16 expert contributors")
        if len({c.case_id for c in self.cases}) != len(self.cases):
            raise ValueError("Duplicate calibration cases")
        return self


class GradePolicy(AssessmentBase):
    __tablename__ = "grade_policies"
    policy_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_version_id: Mapped[str] = mapped_column(String(36), index=True)
    plan_digest: Mapped[str] = mapped_column(String(64))
    rules: Mapped[dict] = mapped_column(JSON)
    rules_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    retired_by: Mapped[str | None] = mapped_column(String(36))
    retirement_reason: Mapped[str | None] = mapped_column(String(2000))
    approved_by: Mapped[str | None] = mapped_column(String(36), index=True)
    calibration: Mapped[dict | None] = mapped_column(JSON)
    calibration_digest: Mapped[str | None] = mapped_column(String(64))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class GradeDecision(AssessmentBase):
    __tablename__ = "grade_decisions"
    __table_args__ = (UniqueConstraint("session_id"),)
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    specialization: Mapped[str] = mapped_column(String(100))
    target_grade: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    score: Mapped[int | None]
    competency_scores: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_grade: Mapped[str | None] = mapped_column(String(16))


class CandidateGrade(AssessmentBase):
    __tablename__ = "candidate_grades"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    specialization: Mapped[str] = mapped_column(String(100), primary_key=True)
    grade: Mapped[str] = mapped_column(String(16))
    decision_id: Mapped[str] = mapped_column(String(36))
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    change_available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyCommand(Contract):
    plan_version_id: UUID
    rules: Rules


class PolicyView(PolicyCommand):
    policy_id: UUID
    status: Literal["draft", "approved", "retired"]
    version: int
    calibrated: bool
    calibration: CalibrationData | None = None
    retirement_reason: str | None = None
    demo: Literal[True] = True


class SessionEvaluation(Contract):
    session_id: UUID
    policy_id: UUID | None
    status: Literal[
        "awaiting_calibration",
        "awaiting_evidence",
        "review_pending",
        "confirmed",
        "rejected",
        "technical_failure",
    ]
    score: int | None = None
    competency_scores: dict[str, int] = Field(default_factory=dict)
    recommended_grade: Grade | None = None
    confirmed_grade: Grade | None = None
    evidence_digest: str | None = None
    decision_id: UUID | None = None
    next_attempt_at: datetime | None = None
    grade_change_available_at: datetime | None = None
    demo: Literal[True] = True


class DecisionCommand(Contract):
    action: Literal["confirm", "reject", "technical_failure"]
    evidence_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


router = APIRouter(prefix="/v1", tags=["assessment-grades"])


def policy_view(row):
    return PolicyView(
        policy_id=row.policy_id,
        plan_version_id=row.plan_version_id,
        rules=row.rules,
        status=row.status,
        version=row.version,
        calibrated=row.calibration is not None,
        calibration=row.calibration,
        retirement_reason=row.retirement_reason,
    )


def plan_digest(plan):
    import hashlib

    from reverse_hr.processing_access import canonical

    return hashlib.sha256(
        canonical(
            PolicyPlan(
                plan_version_id=plan.plan_version_id,
                specialization=plan.specialization,
                grade=plan.grade,
                stages=plan.stages,
                test_pins_digest=plan.test_pins_digest,
            )
        )
    ).hexdigest()


class PolicyPlan(Contract):
    plan_version_id: UUID
    specialization: str
    grade: Grade
    stages: list[dict]
    test_pins_digest: str | None


class PolicyBinding(Contract):
    policy_id: UUID
    plan_digest: str
    rules_digest: str
    calibration_digest: str | None
    approved_by: UUID | None


def policy_digest(row):
    return digest(
        PolicyBinding(
            policy_id=row.policy_id,
            plan_digest=row.plan_digest,
            rules_digest=row.rules_digest,
            calibration_digest=row.calibration_digest,
            approved_by=row.approved_by,
        )
    )


def pinned_policy(session, row, plan):
    policy, rules = policy_for(session, row.grade_policy_id, plan)
    if row.grade_policy_digest is None or row.grade_policy_digest != policy_digest(policy):
        raise HTTPException(409, "Corrupted session grade policy pin")
    return policy, rules


def policy_for(session, policy_id, plan, *, active=True):
    row = session.scalar(
        select(GradePolicy)
        .where(GradePolicy.policy_id == str(policy_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        plan is None
        or row is None
        or row.plan_version_id != plan.plan_version_id
        or row.plan_digest != plan_digest(plan)
        or (active and row.status != "approved")
    ):
        raise HTTPException(409, "Approved calibrated policy required for this plan")
    for owner in calibration_owners(row):
        from reverse_hr.domains.assessment_sessions import AssessmentSubject

        subject = session.get(AssessmentSubject, owner)
        if subject is not None and subject.blocked:
            raise HTTPException(409)
    rules = Rules.model_validate(row.rules)
    if digest(rules) != row.rules_digest:
        raise HTTPException(409, "Corrupted grade policy")
    if row.status == "approved" or row.calibration is not None:
        data = CalibrationData.model_validate(row.calibration)
        if digest(data) != row.calibration_digest or row.approved_by == row.created_by:
            raise HTTPException(409, "Corrupted calibration approval")
        validate_calibration(rules, data)
    return row, rules


def weighted(scores, rules):
    if set(scores) != set(rules.weights):
        raise ValueError("Competency coverage differs from policy")
    total = sum(scores[k] * weight for k, weight in rules.weights.items()) // 100
    passed = total >= rules.pass_score and all(
        scores[k] >= value for k, value in rules.minimums.items()
    )
    return total, passed


def validate_calibration(rules, data):
    if len(data.cases) < rules.minimum_validation_cases:
        raise HTTPException(409, "Insufficient held-out calibration cases")
    positive = sum(c.labels[0].passed for c in data.cases)
    if min(positive, len(data.cases) - positive) < 5:
        raise HTTPException(409, "Calibration requires positive and negative expert examples")
    try:
        accuracy = sum(weighted(c.scores, rules)[1] == c.labels[0].passed for c in data.cases)
    except ValueError as exc:
        raise HTTPException(409) from exc
    for expected in (True, False):
        group = [c for c in data.cases if c.labels[0].passed == expected]
        correct = sum(weighted(c.scores, rules)[1] == expected for c in group)
        if correct * 100 < rules.minimum_accuracy_percent * len(group):
            raise HTTPException(409, "Calibration class accuracy below policy threshold")
    if accuracy * 100 < rules.minimum_accuracy_percent * len(data.cases):
        raise HTTPException(409, "Calibration accuracy below policy threshold")


@router.post("/grade-policies", response_model=PolicyView, status_code=201)
def create_policy(request: Request, actor: Actor, body: PolicyCommand, idempotency: CommandKey):
    actor.require("content_admin", mfa=True)

    def guard(session):
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)

    def change(session):
        plan = session.get(PlanVersion, str(body.plan_version_id))
        if plan is None or plan.status != "published":
            raise HTTPException(409)
        competencies = set()
        for stage in plan.stages:
            revision = session.get(ContentRevision, stage["revision_id"])
            task = next(t for t in revision.content["tasks"] if t["key"] == stage["task_key"])
            competencies.update(c["competency"] for c in task["rubric"])
        if set(body.rules.weights) != competencies:
            raise HTTPException(422, "Policy must cover all plan competencies")
        row = GradePolicy(
            policy_id=str(uuid4()),
            plan_version_id=plan.plan_version_id,
            plan_digest=plan_digest(plan),
            rules=body.rules.model_dump(mode="json"),
            rules_digest=digest(body.rules),
            status="draft",
            version=1,
            created_by=str(actor.subject),
        )
        session.add(row)
        return {"policy_id": row.policy_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_grade_policy",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, value: policy_view(
            session.get(GradePolicy, value["policy_id"])
        ).model_dump(mode="json"),
    )


@router.post("/grade-policies/{policy_id}/approve", response_model=PolicyView)
def approve_policy(
    request: Request,
    actor: Actor,
    policy_id: UUID,
    body: CalibrationData,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)

    def guard(session):
        row = session.get(GradePolicy, str(policy_id))
        if row is None:
            raise HTTPException(404)
        for owner in sorted(
            {row.created_by, str(actor.subject)}
            | {str(label.expert_id) for case in body.cases for label in case.labels}
        ):
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))
        if row.created_by == str(actor.subject):
            raise HTTPException(403)

    def change(session):
        row = session.scalar(
            select(GradePolicy)
            .where(GradePolicy.policy_id == str(policy_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.status != "draft" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        plan = session.get(PlanVersion, row.plan_version_id)
        if plan.status != "published" or plan_digest(plan) != row.plan_digest:
            raise HTTPException(409)
        rules = Rules.model_validate(row.rules)
        if digest(rules) != row.rules_digest:
            raise HTTPException(409)
        validate_calibration(rules, body)
        row.calibration, row.calibration_digest = body.model_dump(mode="json"), digest(body)
        row.status, row.version, row.approved_by, row.approved_at = (
            "approved",
            2,
            str(actor.subject),
            datetime.now(UTC),
        )
        emit(
            session,
            request,
            row.policy_id,
            row.version,
            "grade_policy_approved",
            {"policy_id": policy_id},
        )
        return policy_view(row).model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"approve_grade_policy:{policy_id}",
        idempotency,
        {"version": int(if_match.strip('"')), "body": body.model_dump(mode="json")},
        change,
        guard=guard,
        present=lambda session, _: policy_view(session.get(GradePolicy, str(policy_id))).model_dump(
            mode="json"
        ),
    )


def admission(session, candidate, plan, policy_id):
    policy, rules = policy_for(session, policy_id, plan)
    now = datetime.now(UTC)
    prior = list(
        session.scalars(
            select(GradeDecision).where(
                GradeDecision.candidate_id == str(candidate),
                GradeDecision.specialization == plan.specialization,
                GradeDecision.target_grade == plan.grade,
            )
        )
    )
    from reverse_hr.domains.assessment_appeals import effective_decision

    prior = [effective_decision(session, d) for d in prior]
    if any(utc(d.next_attempt_at) > now for d in prior):
        raise HTTPException(409, "Repeat attempt cooldown active")
    # A second scored attempt cannot bypass an unfinished first decision.
    for pending in session.scalars(
        select(PracticalSession).where(
            PracticalSession.candidate_id == str(candidate),
            PracticalSession.grade_policy_id.is_not(None),
            PracticalSession.status == "submitted",
        )
    ):
        old_plan = session.get(PlanVersion, pending.plan_version_id)
        if (
            old_plan.specialization == plan.specialization
            and old_plan.grade == plan.grade
            and not session.scalar(
                select(GradeDecision.decision_id).where(
                    GradeDecision.session_id == pending.session_id
                )
            )
        ):
            raise HTTPException(409, "Previous attempt awaits a decision")
    grade = session.get(CandidateGrade, (str(candidate), plan.specialization))
    if (
        grade
        and list(Grade).index(Grade(plan.grade)) > list(Grade).index(Grade(grade.grade))
        and utc(grade.change_available_at) > now
    ):
        raise HTTPException(409, "Grade change cooldown active")
    return policy


def aggregate(stages, rules):
    totals = {}
    for stage in stages:
        if rules.required_llm_model is not None and (
            stage.model_attempt_id is None
            or stage.llm_model != rules.required_llm_model
            or stage.llm_prompt_digest != rules.required_llm_prompt_digest
        ):
            return None, {}, False
        if stage.score is None:
            return None, {}, False
        for c in stage.criteria:
            points, maximum = totals.get(c.competency, (0, 0))
            totals[c.competency] = points + c.points, maximum + c.max_points
    if set(totals) != set(rules.weights):
        raise HTTPException(409)
    precise = {k: Fraction(points * 100, maximum) for k, (points, maximum) in totals.items()}
    scores = {k: int(value) for k, value in precise.items()}
    score, passed = weighted(precise, rules)
    return int(score), scores, passed


def gather(request, row):
    with Session(request.app.state.engine) as session:
        states = [session.get(StageState, spec["stage_id"]) for spec in row.stages]
        if any(s is None or s.status != "submitted" for s in states):
            raise HTTPException(409)
        expected = [
            (
                spec,
                state.snapshot_version,
                state.digest,
                UUID(state.workspace_id),
                UUID(state.snapshot_id),
            )
            for spec, state in zip(row.stages, states, strict=True)
        ]
    stages = []
    for spec, version, sha, workspace, snapshot in expected:
        score = request.app.state.grade_access.fetch(
            candidate_id=UUID(row.candidate_id),
            session_id=UUID(row.session_id),
            stage_id=UUID(spec["stage_id"]),
            workspace_id=workspace,
            snapshot_id=snapshot,
        )
        if (
            score.snapshot_version != version
            or score.snapshot_digest != sha
            or str(score.revision_id) != spec["revision_id"]
            or score.task_key != spec["task_key"]
        ):
            raise HTTPException(409)
        with Session(request.app.state.engine) as session:
            revision = session.get(ContentRevision, spec["revision_id"])
            from reverse_hr.domains.assessment import ContentPackage

            package = ContentPackage.model_validate(revision.content)
            task = next(t for t in package.tasks if t.key == spec["task_key"])
            if score.content_digest != digest(package) or [
                (c.criterion_key, c.competency, c.max_points, c.evidence_type)
                for c in score.criteria
            ] != [(c.key, c.competency, c.points, c.evidence) for c in task.rubric]:
                raise HTTPException(409)
        stages.append(score)
    return stages


class SessionEvidence(Contract):
    session_id: UUID
    policy_id: UUID
    stages: list[StageScore]


def evaluation(session, row, stages=None):
    plan = session.get(PlanVersion, row.plan_version_id)
    grade = session.get(CandidateGrade, (row.candidate_id, plan.specialization))
    base = dict(
        session_id=row.session_id,
        policy_id=row.grade_policy_id,
        confirmed_grade=grade.grade if grade else None,
        grade_change_available_at=utc(grade.change_available_at) if grade else None,
    )
    decision = session.scalar(
        select(GradeDecision).where(GradeDecision.session_id == row.session_id)
    )
    if decision:
        from reverse_hr.domains.assessment_appeals import effective_decision

        decision = effective_decision(session, decision)
        return SessionEvaluation(
            **base,
            status=decision.status,
            score=decision.score,
            competency_scores=decision.competency_scores,
            decision_id=decision.decision_id,
            next_attempt_at=utc(decision.next_attempt_at),
        )
    if row.grade_policy_id is None:
        if row.grade_policy_digest is not None:
            raise HTTPException(409)
        return SessionEvaluation(**base, status="awaiting_calibration")
    policy, rules = pinned_policy(session, row, plan)
    score, competencies, passed = aggregate(stages or [], rules) if stages else (None, {}, False)
    evidence = SessionEvidence(
        session_id=row.session_id, policy_id=row.grade_policy_id, stages=stages or []
    )
    return SessionEvaluation(
        **base,
        status="review_pending" if score is not None else "awaiting_evidence",
        score=score,
        competency_scores=competencies,
        recommended_grade=plan.grade if passed else None,
        evidence_digest=digest(evidence),
    )


def access_row(request, actor, session_id, *, reviewer=False):
    actor.require("assessment_reviewer" if reviewer else "candidate", mfa=reviewer)
    with Session(request.app.state.engine) as session:
        row = session.get(PracticalSession, str(session_id))
        if row is None or (not reviewer and row.candidate_id != str(actor.subject)):
            raise HTTPException(404)
        if reviewer and row.candidate_id == str(actor.subject):
            raise HTTPException(403)
        request.app.state.processing_access.check_assessment(
            UUID(row.candidate_id), UUID(row.consent_id)
        )
        session.expunge(row)
        return row


@router.get("/assessment-sessions/{session_id}/evaluation", response_model=SessionEvaluation)
def get_evaluation(request: Request, actor: Actor, session_id: UUID):
    row = access_row(request, actor, session_id)
    with Session(request.app.state.engine) as session:
        completed = session.scalar(
            select(GradeDecision.decision_id).where(GradeDecision.session_id == row.session_id)
        )
    stages = (
        gather(request, row)
        if row.grade_policy_id and row.status == "submitted" and not completed
        else None
    )
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, row.candidate_id)
        request.app.state.processing_access.check_assessment(
            UUID(row.candidate_id), UUID(row.consent_id)
        )
        current = session.get(PracticalSession, row.session_id)
        if current is None:
            raise HTTPException(404)
        return evaluation(session, current, stages)


@router.get("/assessment-grade-reviews/{session_id}", response_model=SessionEvaluation)
def grade_review(request: Request, actor: Actor, session_id: UUID):
    row = access_row(request, actor, session_id, reviewer=True)
    with Session(request.app.state.engine) as session:
        completed = session.scalar(
            select(GradeDecision.decision_id).where(GradeDecision.session_id == row.session_id)
        )
    stages = (
        gather(request, row)
        if row.grade_policy_id and row.status == "submitted" and not completed
        else None
    )
    with Session(request.app.state.engine) as session, session.begin():
        for owner in sorted(policy_owners(request, session, row) | {str(actor.subject)}):
            subject_lock(session, owner)
        request.app.state.processing_access.check_assessment(
            UUID(row.candidate_id), UUID(row.consent_id)
        )
        request.app.state.processing_access.check(actor.subject)
        current = session.get(PracticalSession, row.session_id)
        if current is None:
            raise HTTPException(404)
        return evaluation(session, current, stages)


@router.post("/assessment-grade-reviews/{session_id}/decisions", response_model=SessionEvaluation)
def decide_grade(
    request: Request, actor: Actor, session_id: UUID, body: DecisionCommand, idempotency: CommandKey
):
    row = access_row(request, actor, session_id, reviewer=True)
    with Session(request.app.state.engine) as session:
        previous = session.scalar(
            select(GradeDecision.decision_id).where(GradeDecision.session_id == row.session_id)
        )
    stages = gather(request, row) if body.action != "technical_failure" and not previous else []

    def guard(session):
        for owner in sorted(policy_owners(request, session, row) | {str(actor.subject)}):
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))
        request.app.state.processing_access.check(actor.subject)
        request.app.state.processing_access.check_assessment(
            UUID(row.candidate_id), UUID(row.consent_id)
        )
        current = session.get(PracticalSession, row.session_id)
        if (
            current is None
            or current.version != row.version
            or current.status not in {"submitted", "completed"}
        ):
            raise HTTPException(409)

    def change(session):
        current = session.get(PracticalSession, row.session_id)
        if session.scalar(
            select(GradeDecision.decision_id).where(GradeDecision.session_id == row.session_id)
        ):
            raise HTTPException(409)
        plan = session.get(PlanVersion, current.plan_version_id)
        policy, rules = pinned_policy(session, current, plan)
        proposal = evaluation(session, current, stages)
        if body.action != "technical_failure" and (
            proposal.status != "review_pending" or proposal.evidence_digest != body.evidence_digest
        ):
            raise HTTPException(409, "Complete current evidence required")
        if body.action == "confirm" and proposal.recommended_grade is None:
            raise HTTPException(409, "Thresholds and competency minimums not met")
        now, decision_id = datetime.now(UTC), str(uuid4())
        grade = session.get(CandidateGrade, (row.candidate_id, plan.specialization))
        upgrade = body.action == "confirm" and (
            grade is None
            or list(Grade).index(Grade(plan.grade)) > list(Grade).index(Grade(grade.grade))
        )
        if upgrade and grade and utc(grade.change_available_at) > now:
            raise HTTPException(409, "Grade change cooldown active")
        if upgrade:
            if grade is None:
                grade = CandidateGrade(
                    candidate_id=row.candidate_id, specialization=plan.specialization
                )
                session.add(grade)
            grade.grade, grade.decision_id, grade.changed_at = plan.grade, decision_id, now
            grade.change_available_at = now + timedelta(seconds=rules.grade_change_seconds)
        decision = GradeDecision(
            decision_id=decision_id,
            session_id=row.session_id,
            candidate_id=row.candidate_id,
            reviewer_id=str(actor.subject),
            specialization=plan.specialization,
            target_grade=plan.grade,
            status={
                "confirm": "confirmed",
                "reject": "rejected",
                "technical_failure": "technical_failure",
            }[body.action],
            score=proposal.score if body.action != "technical_failure" else None,
            competency_scores=proposal.competency_scores
            if body.action != "technical_failure"
            else {},
            evidence=SessionEvidence(
                session_id=row.session_id, policy_id=current.grade_policy_id, stages=stages
            ).model_dump(mode="json"),
            reason=body.reason,
            created_at=now,
            next_attempt_at=now
            + timedelta(seconds=rules.retry_seconds if body.action != "technical_failure" else 0),
            confirmed_grade=grade.grade if grade else None,
        )
        current.status, current.version = "completed", current.version + 1
        session.add(decision)
        session.flush()
        emit(
            session,
            request,
            row.session_id,
            current.version,
            "grade_decision_recorded",
            {
                "candidate_id": UUID(row.candidate_id),
                "session_id": session_id,
                "decision_id": UUID(decision_id),
                "reviewer_id": actor.subject,
            },
        )
        return evaluation(session, current).model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"grade_decision:{session_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=guard,
        present=lambda session, _: evaluation(
            session, session.get(PracticalSession, row.session_id)
        ).model_dump(mode="json"),
    )


def calibration_owners(policy):
    owners = {policy.created_by, policy.approved_by, policy.retired_by} - {None}
    if policy.calibration:
        data = CalibrationData.model_validate(policy.calibration)
        owners |= {str(label.expert_id) for case in data.cases for label in case.labels}
    return owners


def policy_owners(request, session, row):
    if row.grade_policy_id is None:
        return {row.candidate_id}
    policy = session.get(GradePolicy, row.grade_policy_id)
    if policy is None:
        raise HTTPException(409)
    return {row.candidate_id} | calibration_owners(policy)


def purge(session, candidate):
    session.execute(delete(GradeDecision).where(GradeDecision.candidate_id == candidate))
    session.execute(delete(CandidateGrade).where(CandidateGrade.candidate_id == candidate))


@router.get("/grade-policies/{policy_id}", response_model=PolicyView)
def get_policy(request: Request, actor: Actor, policy_id: UUID):
    actor.require("content_admin", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(GradePolicy, str(policy_id))
        if row is None:
            raise HTTPException(404)
        for owner in sorted({str(actor.subject)} | calibration_owners(row)):
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))
        policy_for(session, policy_id, session.get(PlanVersion, row.plan_version_id), active=False)
        return policy_view(row)


class RetirementCommand(Contract):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


@router.post("/grade-policies/{policy_id}/retire", response_model=PolicyView)
def retire_policy(
    request: Request,
    actor: Actor,
    policy_id: UUID,
    body: RetirementCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)

    def guard(session):
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)

    def change(session):
        row = session.scalar(
            select(GradePolicy)
            .where(GradePolicy.policy_id == str(policy_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise HTTPException(404)
        if row.status == "retired" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.status, row.version = "retired", row.version + 1
        row.retired_by, row.retirement_reason = str(actor.subject), body.reason
        emit(
            session,
            request,
            row.policy_id,
            row.version,
            "grade_policy_retired",
            {"policy_id": policy_id, "actor_id": actor.subject},
        )
        return policy_view(row).model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"retire_grade_policy:{policy_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": int(if_match.strip('"'))},
        change,
        guard=guard,
        present=lambda session, _: policy_view(session.get(GradePolicy, str(policy_id))).model_dump(
            mode="json"
        ),
    )
