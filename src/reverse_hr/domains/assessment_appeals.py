"""Versioned independent appeals; original decisions and submitted evidence stay immutable."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract, Grade
from reverse_hr.db import IdempotencyRecord, Outbox, enqueue
from reverse_hr.domains.assessment import AssessmentBase
from reverse_hr.domains.assessment_evaluation import MaterialNonce
from reverse_hr.domains.assessment_grades import (
    CandidateGrade,
    GradeDecision,
    GradePolicy,
    Rules,
    SessionEvidence,
    aggregate,
    gather,
    policy_digest,
    policy_for,
    policy_owners,
)
from reverse_hr.domains.assessment_sessions import (
    PlanVersion,
    PracticalSession,
    emit,
    subject_lock,
    utc,
)
from reverse_hr.events import EventEnvelope
from reverse_hr.market_access import Signature, respond
from reverse_hr.market_contracts import AppealNoticeView, MarketReceipt, MarketRequest
from reverse_hr.test_suites import digest


class Appeal(AssessmentBase):
    __tablename__ = "assessment_appeals"
    appeal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True, unique=True)
    decision_id: Mapped[str] = mapped_column(String(36), unique=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(5000))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    reviewer_id: Mapped[str | None] = mapped_column(String(36), index=True)
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    filing_deadline: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppealAction(AssessmentBase):
    __tablename__ = "assessment_appeal_actions"
    __table_args__ = (UniqueConstraint("appeal_id", "version"),)
    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    appeal_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int]
    action: Mapped[str] = mapped_column(String(24))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AppealDecision(AssessmentBase):
    __tablename__ = "assessment_appeal_decisions"
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    appeal_id: Mapped[str] = mapped_column(String(36), unique=True)
    original_decision_id: Mapped[str] = mapped_column(String(36), unique=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    session_version: Mapped[int]
    previous_session_version: Mapped[int]
    specialization: Mapped[str] = mapped_column(String(100))
    target_grade: Mapped[str] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    score: Mapped[int | None]
    competency_scores: Mapped[dict] = mapped_column(JSON)
    evidence: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    confirmed_grade: Mapped[str | None] = mapped_column(String(16))


class AppealNotice(AssessmentBase):
    __tablename__ = "assessment_appeal_notices"
    notice_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    appeal_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))


class AppealCreate(Contract):
    decision_id: UUID
    reason: str = Field(min_length=1, max_length=5000, pattern=r"\S")


class AppealResolution(Contract):
    action: Literal["uphold", "change"]
    status: Literal["confirmed", "rejected", "technical_failure"]
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class AppealView(Contract):
    appeal_id: UUID
    session_id: UUID
    decision_id: UUID
    candidate_id: UUID
    reason: str
    status: Literal["submitted", "in_review", "resolved", "withdrawn"]
    version: int
    reviewer_id: UUID | None
    submitted_at: datetime
    filing_deadline: datetime
    review_due_at: datetime
    overdue: bool
    resolution: dict | None


class AppealEvidence(Contract):
    appeal_id: UUID
    original: SessionEvidence
    current: SessionEvidence
    evidence_digest: str
    score: int | None
    competency_scores: dict[str, int]
    recommended_status: Literal["confirmed", "rejected", "technical_failure"]
    repeated_review_complete: bool


router = APIRouter(prefix="/v1/assessment-appeals", tags=["assessment-appeals"])


def effective_decision(session, decision):
    return (
        session.scalar(
            select(AppealDecision).where(
                AppealDecision.original_decision_id == decision.decision_id
            )
        )
        or decision
    )


def view(session, row):
    decision = session.scalar(
        select(AppealDecision).where(AppealDecision.appeal_id == row.appeal_id)
    )
    return AppealView(
        appeal_id=row.appeal_id,
        session_id=row.session_id,
        decision_id=row.decision_id,
        candidate_id=row.candidate_id,
        reason=row.reason,
        status=row.status,
        version=row.version,
        reviewer_id=row.reviewer_id,
        submitted_at=utc(row.submitted_at),
        filing_deadline=utc(row.filing_deadline),
        review_due_at=utc(row.review_due_at),
        overdue=row.status in {"submitted", "in_review"}
        and utc(row.review_due_at) < datetime.now(UTC),
        resolution=dict(
            decision_id=decision.decision_id,
            action=decision.action,
            status=decision.status,
            score=decision.score,
            competency_scores=decision.competency_scores,
            reason=decision.reason,
            created_at=utc(decision.created_at).isoformat(),
        )
        if decision
        else None,
    ).model_dump(mode="json")


def original_owners(original):
    evidence = SessionEvidence.model_validate(original.evidence)
    return {original.reviewer_id} | {str(s.reviewer_id) for s in evidence.stages if s.reviewer_id}


def authorized(request, session, actor, row, *, reviewer=False, assigned=False):
    actor.require("assessment_reviewer" if reviewer else "candidate", mfa=reviewer)
    original = session.get(GradeDecision, row.decision_id)
    attempt = session.get(PracticalSession, row.session_id)
    if original is None or attempt is None:
        raise HTTPException(404)
    if reviewer:
        from reverse_hr.review_sla import assignment_guard

        assignment_guard(session, "assessment", "assessment_appeal", row.appeal_id, actor)
        if str(actor.subject) in original_owners(original) | policy_owners(
            request, session, attempt
        ):
            raise HTTPException(403)
        if assigned and row.reviewer_id != str(actor.subject):
            raise HTTPException(403)
    elif row.candidate_id != str(actor.subject):
        raise HTTPException(404)
    owners = (
        policy_owners(request, session, attempt) | original_owners(original) | {str(actor.subject)}
    )
    if row.reviewer_id:
        owners.add(row.reviewer_id)
    for owner in sorted(owners):
        subject_lock(session, owner)
        request.app.state.processing_access.check(UUID(owner))
    request.app.state.processing_access.check_assessment(
        UUID(row.candidate_id), UUID(attempt.consent_id)
    )
    return original, attempt


def action(session, request, row, actor, kind):
    session.add(
        AppealAction(
            action_id=str(uuid4()),
            appeal_id=row.appeal_id,
            candidate_id=row.candidate_id,
            actor_id=str(actor.subject),
            version=row.version,
            action=kind,
            at=datetime.now(UTC),
        )
    )
    emit(
        session,
        request,
        row.appeal_id,
        row.version,
        "appeal_" + kind,
        {"candidate_id": UUID(row.candidate_id), "appeal_id": UUID(row.appeal_id)},
    )
    if kind in {"submitted", "review_started", "resolved"}:
        notice = AppealNotice(
            notice_id=str(uuid4()),
            appeal_id=row.appeal_id,
            candidate_id=row.candidate_id,
            author_id=str(actor.subject),
            kind="appeal_" + kind,
        )
        session.add(notice)
        enqueue(
            session,
            EventEnvelope(
                producer="assessment",
                event_type="assessment.appeal_notification_requested.v1",
                correlation_id=request.state.trace_id,
                aggregate_id=UUID(notice.notice_id),
                aggregate_version=1,
                payload={
                    "notice_id": UUID(notice.notice_id),
                    "appeal_id": UUID(row.appeal_id),
                    "candidate_id": UUID(row.candidate_id),
                    "author_id": actor.subject,
                },
            ),
        )


@router.post("", response_model=AppealView, status_code=201)
def submit(request: Request, actor: Actor, body: AppealCreate, idempotency: CommandKey):
    actor.require("candidate")

    def guard(session):
        subject_lock(session, actor.subject)
        original = session.get(GradeDecision, str(body.decision_id))
        if original is None or original.candidate_id != str(actor.subject):
            raise HTTPException(404)
        attempt = session.get(PracticalSession, original.session_id)
        request.app.state.processing_access.check_assessment(
            actor.subject, UUID(attempt.consent_id)
        )

    def change(session):
        original = session.get(GradeDecision, str(body.decision_id))
        if session.scalar(select(Appeal).where(Appeal.decision_id == original.decision_id)):
            raise HTTPException(409, "One appeal per result")
        now = datetime.now(UTC)
        deadline = utc(original.created_at) + timedelta(
            seconds=request.app.state.settings.appeal_filing_seconds
        )
        if now > deadline:
            raise HTTPException(409, "Appeal filing deadline expired")
        row = Appeal(
            appeal_id=str(uuid4()),
            session_id=original.session_id,
            decision_id=original.decision_id,
            candidate_id=str(actor.subject),
            reason=body.reason,
            status="submitted",
            version=1,
            submitted_at=now,
            filing_deadline=deadline,
            review_due_at=now + timedelta(seconds=request.app.state.settings.appeal_review_seconds),
        )
        session.add(row)
        action(session, request, row, actor, "submitted")
        return {"appeal_id": row.appeal_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "appeal_submit",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, value: view(session, session.get(Appeal, value["appeal_id"])),
    )


def listing(request, actor, after, *, reviewer):
    actor.require("assessment_reviewer" if reviewer else "candidate", mfa=reviewer)
    request.app.state.processing_access.check(actor.subject)
    result, cursor = [], str(after) if after else None
    while len(result) < 20:
        # No subject fences span different cases: each case has one global lock order.
        with Session(request.app.state.engine) as session:
            query = select(Appeal.appeal_id)
            query = (
                query.where(Appeal.status.in_(["submitted", "in_review"]))
                if reviewer
                else query.where(Appeal.candidate_id == str(actor.subject))
            )
            if cursor:
                query = query.where(Appeal.appeal_id > cursor)
            ids = list(session.scalars(query.order_by(Appeal.appeal_id).limit(20)))
        if not ids:
            break
        for item in ids:
            cursor = item
            with Session(request.app.state.engine) as session, session.begin():
                row = session.get(Appeal, item)
                if row is None or (reviewer and row.status not in {"submitted", "in_review"}):
                    continue
                try:
                    authorized(request, session, actor, row, reviewer=reviewer)
                except HTTPException as exc:
                    if reviewer and exc.status_code in {403, 409}:
                        continue
                    raise
                result.append(view(session, row))
            if len(result) == 20:
                break
    return result


@router.get("", response_model=list[AppealView])
def own_list(request: Request, actor: Actor, after: UUID | None = None):
    return listing(request, actor, after, reviewer=False)


@router.get("/queue", response_model=list[AppealView])
def queue(request: Request, actor: Actor, after: UUID | None = None):
    return listing(request, actor, after, reviewer=True)


@router.get("/{appeal_id}", response_model=AppealView)
def get(request: Request, actor: Actor, appeal_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(Appeal, str(appeal_id))
        if row is None:
            raise HTTPException(404)
        authorized(request, session, actor, row, reviewer=str(actor.subject) != row.candidate_id)
        return view(session, row)


def command(request, actor, appeal_id, key, expected, kind, body, change, *, reviewer):
    def guard(session):
        # Read once for lock ordering, then serialize every mutation on candidate's fence.
        row = session.get(Appeal, str(appeal_id))
        if row is None:
            raise HTTPException(404)
        authorized(request, session, actor, row, reviewer=reviewer, assigned=kind == "resolve")

    def update(session):
        row = session.scalar(
            select(Appeal)
            .where(Appeal.appeal_id == str(appeal_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.version != int(expected.strip('"')):
            raise HTTPException(409)
        change(session, row)
        return {"appeal_id": row.appeal_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"appeal_{kind}:{appeal_id}",
        key,
        {"version": expected, "body": body},
        update,
        guard=guard,
        present=lambda session, value: view(session, session.get(Appeal, value["appeal_id"])),
    )


@router.post("/{appeal_id}/claim", response_model=AppealView)
def claim(
    request: Request,
    actor: Actor,
    appeal_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session, row):
        if row.status != "submitted":
            raise HTTPException(409)
        row.status, row.reviewer_id, row.version = "in_review", str(actor.subject), row.version + 1
        action(session, request, row, actor, "review_started")

    return command(
        request, actor, appeal_id, idempotency, if_match, "claim", {}, change, reviewer=True
    )


@router.post("/{appeal_id}/withdraw", response_model=AppealView)
def withdraw(
    request: Request,
    actor: Actor,
    appeal_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session, row):
        if row.status not in {"submitted", "in_review"}:
            raise HTTPException(409)
        row.status, row.version = "withdrawn", row.version + 1
        action(session, request, row, actor, "withdrawn")

    return command(
        request, actor, appeal_id, idempotency, if_match, "withdraw", {}, change, reviewer=False
    )


def appeal_policy(session, attempt, plan):
    policy, rules = policy_for(session, attempt.grade_policy_id, plan, active=False)
    if attempt.grade_policy_digest != policy_digest(policy):
        raise HTTPException(409)
    return policy, rules


def repeated(original, stages, reviewer):
    old = SessionEvidence.model_validate(original.evidence)
    previous = {str(s.review_id) for s in old.stages if s.review_id}
    return bool(stages) and all(
        s.review_id
        and str(s.review_id) not in previous
        and str(s.reviewer_id) == str(reviewer)
        and (
            index >= len(old.stages)
            or old.stages[index].model_attempt_id is None
            or s.model_attempt_id is not None
        )
        for index, s in enumerate(stages)
    )


def evidence(request, actor, appeal_id):
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(Appeal, str(appeal_id))
        if row is None:
            raise HTTPException(404)
        original, attempt = authorized(request, session, actor, row, reviewer=True, assigned=True)
        if row.status == "resolved":
            final = session.scalar(
                select(AppealDecision).where(AppealDecision.appeal_id == row.appeal_id)
            )
            current = SessionEvidence.model_validate(final.evidence)
            proof = AppealEvidence(
                appeal_id=appeal_id,
                original=original.evidence,
                current=current,
                evidence_digest=digest(current),
                score=final.score,
                competency_scores=final.competency_scores,
                recommended_status=final.status,
                repeated_review_complete=True,
            )
            return row.version, current.stages, proof
        if row.status != "in_review":
            raise HTTPException(409)
        session.expunge(attempt)
        snapshot = (row.version, original.evidence)
    stages = gather(request, attempt)  # Signed Evaluation proof checked outside Assessment locks.
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(Appeal, str(appeal_id))
        if row is None or row.version != snapshot[0]:
            raise HTTPException(409)
        original, attempt = authorized(request, session, actor, row, reviewer=True, assigned=True)
        plan = session.get(PlanVersion, attempt.plan_version_id)
        _, rules = appeal_policy(session, attempt, plan)
        score, scores, passed = aggregate(stages, rules)
        current = SessionEvidence(
            session_id=row.session_id, policy_id=attempt.grade_policy_id, stages=stages
        )
        return (
            row.version,
            stages,
            AppealEvidence(
                appeal_id=appeal_id,
                original=snapshot[1],
                current=current,
                evidence_digest=digest(current),
                score=score,
                competency_scores=scores,
                recommended_status="technical_failure"
                if score is None
                else "confirmed"
                if passed
                else "rejected",
                repeated_review_complete=repeated(original, stages, actor.subject),
            ),
        )


@router.get("/{appeal_id}/evidence", response_model=AppealEvidence)
def workspace(request: Request, actor: Actor, appeal_id: UUID):
    return evidence(request, actor, appeal_id)[2]


def recompute_grade(session, candidate, specialization, rules, original):
    decisions = [
        effective_decision(session, d)
        for d in session.scalars(
            select(GradeDecision).where(
                GradeDecision.candidate_id == candidate,
                GradeDecision.specialization == specialization,
            )
        )
    ]
    valid = [d for d in decisions if d.status == "confirmed"]
    row = session.get(CandidateGrade, (candidate, specialization))
    if not valid:
        if row:
            session.delete(row)
        return None
    winner = max(
        valid,
        key=lambda d: (list(Grade).index(Grade(d.target_grade)), utc(d.created_at), d.decision_id),
    )
    if row is None:
        row = CandidateGrade(candidate_id=candidate, specialization=specialization)
        session.add(row)
    if row.grade != winner.target_grade:
        root = (
            session.get(GradeDecision, winner.original_decision_id)
            if isinstance(winner, AppealDecision)
            else winner
        )
        attempt = session.get(PracticalSession, root.session_id)
        policy = session.get(GradePolicy, attempt.grade_policy_id)
        row.changed_at = utc(root.created_at)
        row.change_available_at = row.changed_at + timedelta(
            seconds=Rules.model_validate(policy.rules).grade_change_seconds
        )
    row.grade, row.decision_id = winner.target_grade, winner.decision_id
    return row.grade


@router.post("/{appeal_id}/resolve", response_model=AppealView)
def resolve(
    request: Request,
    actor: Actor,
    appeal_id: UUID,
    body: AppealResolution,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    version, stages, proof = evidence(request, actor, appeal_id)

    def change(session, row):
        if (
            row.status != "in_review"
            or row.version != version
            or not proof.repeated_review_complete
        ):
            raise HTTPException(409, "Independent repeated review of every stage required")
        original = session.get(GradeDecision, row.decision_id)
        if body.evidence_digest != proof.evidence_digest or body.status != proof.recommended_status:
            raise HTTPException(409, "Current verified evidence and calibrated thresholds required")
        if body.action == "uphold" and (
            body.status != original.status
            or proof.score != original.score
            or proof.competency_scores != original.competency_scores
        ):
            raise HTTPException(409, "Use change for a changed result")
        attempt = session.get(PracticalSession, row.session_id)
        _, rules = appeal_policy(
            session, attempt, session.get(PlanVersion, attempt.plan_version_id)
        )
        decision = AppealDecision(
            decision_id=str(uuid4()),
            appeal_id=row.appeal_id,
            original_decision_id=original.decision_id,
            session_id=row.session_id,
            candidate_id=row.candidate_id,
            reviewer_id=str(actor.subject),
            previous_session_version=attempt.version,
            session_version=attempt.version + 1,
            specialization=original.specialization,
            target_grade=original.target_grade,
            action=body.action,
            status=body.status,
            score=proof.score,
            competency_scores=proof.competency_scores,
            evidence=proof.current.model_dump(mode="json"),
            reason=body.reason,
            created_at=datetime.now(UTC),
            next_attempt_at=utc(original.created_at)
            if body.status == "technical_failure"
            else utc(original.created_at) + timedelta(seconds=rules.retry_seconds),
        )
        session.add(decision)
        session.flush()
        decision.confirmed_grade = recompute_grade(
            session, row.candidate_id, original.specialization, rules, original
        )
        attempt.version += 1
        row.status, row.version = "resolved", row.version + 1
        action(session, request, row, actor, "resolved")
        emit(
            session,
            request,
            row.session_id,
            attempt.version,
            "grade_decision_recorded",
            {
                "candidate_id": UUID(row.candidate_id),
                "session_id": UUID(row.session_id),
                "decision_id": UUID(decision.decision_id),
                "reviewer_id": actor.subject,
            },
        )

    return command(
        request,
        actor,
        appeal_id,
        idempotency,
        if_match,
        "resolve",
        body.model_dump(mode="json"),
        change,
        reviewer=True,
    )


@router.get("/{appeal_id}/history", response_model=list[dict])
def history(request: Request, actor: Actor, appeal_id: UUID, after: int = 0):
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(Appeal, str(appeal_id))
        if row is None:
            raise HTTPException(404)
        authorized(request, session, actor, row, reviewer=str(actor.subject) != row.candidate_id)
        return [
            dict(
                action_id=a.action_id,
                actor_id=a.actor_id,
                version=a.version,
                action=a.action,
                at=utc(a.at).isoformat(),
            )
            for a in session.scalars(
                select(AppealAction)
                .where(AppealAction.appeal_id == str(appeal_id), AppealAction.version > after)
                .order_by(AppealAction.version)
                .limit(20)
            )
        ]


def purge(session, subject):
    from reverse_hr.review_sla import scrub as scrub_sla

    scrub_sla(session, "assessment", subject)
    for row in session.scalars(
        select(Appeal).where(Appeal.reviewer_id == subject, Appeal.status == "in_review")
    ):
        row.status, row.reviewer_id, row.version = "submitted", None, row.version + 1
        session.add(
            AppealAction(
                action_id=str(uuid4()),
                appeal_id=row.appeal_id,
                candidate_id=row.candidate_id,
                actor_id=subject,
                version=row.version,
                action="reviewer_released",
                at=datetime.now(UTC),
            )
        )
    ids = list(session.scalars(select(Appeal.appeal_id).where(Appeal.candidate_id == subject)))
    for table in (AppealDecision, AppealAction, AppealNotice, Appeal):
        session.execute(delete(table).where(table.candidate_id == subject))
    if ids:
        operations = [
            f"appeal_{kind}:{key}" for key in ids for kind in ("claim", "withdraw", "resolve")
        ]
        session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.operation.in_(operations))
        )
        session.execute(
            delete(Outbox).where(
                Outbox.envelope["producer"].as_string() == "assessment",
                Outbox.envelope["payload"]["appeal_id"].as_string().in_(ids),
            )
        )


internal_router = APIRouter(prefix="/internal/v1/market", tags=["internal-appeal-notices"])


@internal_router.post("/appeal-notice", response_model=MarketReceipt)
def notice_permission(request: Request, body: MarketRequest, signature: Signature = None):
    def checker(session):
        notice = session.get(AppealNotice, str(body.notice_id))
        if notice is None or notice.candidate_id != str(body.candidate_id):
            return None, 0
        appeal = session.get(Appeal, notice.appeal_id)
        if appeal is None:
            return None, 0
        try:
            for owner in sorted({notice.candidate_id, notice.author_id}):
                subject_lock(session, owner)
                request.app.state.processing_access.check(UUID(owner))
            attempt = session.get(PracticalSession, appeal.session_id)
            request.app.state.processing_access.check_assessment(
                body.candidate_id, UUID(attempt.consent_id)
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                return None, 0
            raise
        return AppealNoticeView(
            notice_id=notice.notice_id,
            appeal_id=notice.appeal_id,
            candidate_id=notice.candidate_id,
            recipient_id=notice.candidate_id,
            author_id=notice.author_id,
            kind=notice.kind,
        ).model_dump(mode="json"), 1

    return respond(
        request,
        body,
        signature,
        "assessment",
        "appeal-notice",
        MaterialNonce,
        {"notification"},
        checker,
    )
