"""Automatic decisions under pinned calibrated policies and independent rechecks."""

import hashlib
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.automation import AUTOMATIC_REVIEWER, human_owners
from reverse_hr.contracts.core import Grade
from reverse_hr.services.assessment.domain.assessment import AssessmentBase
from reverse_hr.services.assessment.domain.assessment_grades import (
    CandidateGrade,
    GradeDecision,
    SessionEvidence,
    evaluation,
    gather,
    pinned_policy,
    policy_owners,
)
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PlanVersion,
    PracticalSession,
    emit,
    subject_lock,
    utc,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, execute


class AutomaticReview(AssessmentBase):
    __tablename__ = "assessment_automatic_reviews"
    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(24))
    reasons: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    appeal_id: Mapped[str | None] = mapped_column(String(36))
    case_origin: Mapped[str | None] = mapped_column(String(16))


router = APIRouter(prefix="/v1/assessment-automatic", tags=["automatic-grades"])


@router.get("/queue")
def queue(request: Request, actor: Actor, limit: int = 50):
    actor.require("assessment_reviewer", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        rows = session.scalars(
            select(AutomaticReview)
            .where(AutomaticReview.status == "pending")
            .order_by(AutomaticReview.updated_at)
            .limit(max(1, min(limit, 100)))
        )
        result = []
        for row in rows:
            attempt = session.get(PracticalSession, row.session_id)
            if (
                attempt is None
                or row.candidate_id == str(actor.subject)
                or str(actor.subject) in policy_owners(request, session, attempt)
            ):
                continue
            request.app.state.processing_access.check_assessment(
                UUID(row.candidate_id), UUID(attempt.consent_id)
            )
            result.append(
                dict(
                    session_id=row.session_id,
                    reasons=row.reasons,
                    appeal_id=row.appeal_id,
                    evaluation=evaluation(session, attempt).model_dump(mode="json"),
                )
            )
        return result


@router.post("/{session_id}/recheck")
def recheck(request: Request, actor: Actor, session_id: UUID, idempotency: CommandKey):
    actor.require("assessment_reviewer", mfa=True)

    def guard(session):
        row = session.get(PracticalSession, str(session_id))
        if row is None:
            raise HTTPException(404)
        if row.candidate_id == str(actor.subject) or str(actor.subject) in policy_owners(
            request, session, row
        ):
            raise HTTPException(403)
        for owner in human_owners(policy_owners(request, session, row) | {str(actor.subject)}):
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))
        request.app.state.processing_access.check_assessment(
            UUID(row.candidate_id), UUID(row.consent_id)
        )

    def change(session):
        from reverse_hr.services.assessment.domain.assessment_appeals import Appeal

        row = session.get(PracticalSession, str(session_id))
        decision = session.scalar(
            select(GradeDecision).where(GradeDecision.session_id == str(session_id))
        )
        if decision is None or decision.origin != "automatic":
            raise HTTPException(409, "An automatic decision is required")
        existing = session.scalar(select(Appeal).where(Appeal.session_id == str(session_id)))
        created_quality_case = existing is None
        if existing is None:
            now = datetime.now(UTC)
            existing = Appeal(
                appeal_id=str(uuid4()),
                session_id=str(session_id),
                decision_id=decision.decision_id,
                candidate_id=row.candidate_id,
                reason="Independent quality recheck of an automatic result",
                status="submitted",
                version=1,
                reviewer_id=None,
                submitted_at=now,
                filing_deadline=now + timedelta(days=30),
                review_due_at=now + timedelta(days=3),
            )
            session.add(existing)
            emit(
                session,
                request,
                existing.appeal_id,
                1,
                "automatic_recheck_requested",
                {"candidate_id": UUID(row.candidate_id), "session_id": session_id},
            )
        state = session.get(AutomaticReview, str(session_id))
        if state is None:
            state = AutomaticReview(
                session_id=str(session_id),
                candidate_id=row.candidate_id,
                created_at=datetime.now(UTC),
                updated_at=datetime.now(UTC),
                reasons=["requested_recheck"],
                status="pending",
            )
            session.add(state)
        state.appeal_id = existing.appeal_id
        if created_quality_case:
            state.case_origin = "quality"
        state.status = "resolved" if existing.status == "resolved" else "pending"
        return dict(appeal_id=existing.appeal_id)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"automatic_recheck:{session_id}",
        idempotency,
        {"session_id": str(session_id)},
        change,
        guard=guard,
    )


def run_one(request):
    engine = request.app.state.engine
    with Session(engine) as session:
        ids = list(
            session.scalars(
                select(PracticalSession.session_id).where(
                    PracticalSession.status == "submitted",
                    PracticalSession.grade_policy_id.is_not(None),
                )
            )
        )
        times = {
            r.session_id: utc(r.updated_at).timestamp()
            for r in session.scalars(select(AutomaticReview))
        }
        ids.sort(key=lambda key: times.get(key, 0))
    for session_id in ids:
        with Session(engine) as session:
            attempt = session.get(PracticalSession, session_id)
            if attempt is None or session.scalar(
                select(GradeDecision.decision_id).where(GradeDecision.session_id == session_id)
            ):
                continue
            plan = session.get(PlanVersion, attempt.plan_version_id)
            try:
                _, rules = pinned_policy(session, attempt, plan)
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                raise
            if not rules.automatic_decisions:
                continue
            version = attempt.version
            session.expunge(attempt)
        stages = gather(request, attempt)
        with Session(engine) as session, session.begin():
            for owner in sorted(human_owners(policy_owners(request, session, attempt))):
                subject_lock(session, owner)
                request.app.state.processing_access.check(UUID(owner))
            request.app.state.processing_access.check_assessment(
                UUID(attempt.candidate_id), UUID(attempt.consent_id)
            )
            row = session.scalar(
                select(PracticalSession)
                .where(PracticalSession.session_id == session_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                row is None
                or row.version != version
                or row.status != "submitted"
                or session.scalar(
                    select(GradeDecision.decision_id).where(GradeDecision.session_id == session_id)
                )
            ):
                continue
            plan = session.get(PlanVersion, row.plan_version_id)
            _, rules = pinned_policy(session, row, plan)
            if not rules.automatic_decisions:
                continue
            now = datetime.now(UTC)
            state = session.get(AutomaticReview, session_id)
            if state is None:
                state = AutomaticReview(
                    session_id=session_id,
                    candidate_id=row.candidate_id,
                    status="waiting",
                    reasons=[],
                    created_at=now,
                    updated_at=now,
                )
                session.add(state)
            state.updated_at = now
            if any(stage.additional_verification_required for stage in stages):
                state.status, state.reasons = "pending", ["additional_verification_required"]
                return True
            proposal = evaluation(session, row, stages)
            if proposal.score is None:
                # Do not convert a technical wait into a failed grade.
                state.status = (
                    "pending" if now - utc(state.created_at) >= timedelta(minutes=10) else "waiting"
                )
                state.reasons = ["incomplete_evidence"]
                return True
            reasons = []
            if abs(proposal.score - rules.pass_score) <= rules.review_margin:
                reasons.append("grade_boundary")
            if any(
                abs(proposal.competency_scores[key] - minimum) <= rules.review_margin
                for key, minimum in rules.minimums.items()
            ):
                reasons.append("competency_boundary")
            if reasons:
                state.status, state.reasons = "pending", reasons
                return True
            grade = session.get(CandidateGrade, (row.candidate_id, plan.specialization))
            upgrade = proposal.recommended_grade is not None and (
                grade is None
                or list(Grade).index(Grade(plan.grade)) > list(Grade).index(Grade(grade.grade))
            )
            if upgrade and grade and utc(grade.change_available_at) > now:
                state.status, state.reasons = "pending", ["grade_cooldown"]
                return True
            decision_id = str(uuid4())
            if upgrade:
                if grade is None:
                    grade = CandidateGrade(
                        candidate_id=row.candidate_id, specialization=plan.specialization
                    )
                    session.add(grade)
                grade.grade, grade.decision_id, grade.changed_at = plan.grade, decision_id, now
                grade.change_available_at = now + timedelta(seconds=rules.grade_change_seconds)
            decision = GradeDecision(
                origin="automatic",
                decision_id=decision_id,
                session_id=session_id,
                candidate_id=row.candidate_id,
                reviewer_id=str(AUTOMATIC_REVIEWER),
                specialization=plan.specialization,
                target_grade=plan.grade,
                status="confirmed" if proposal.recommended_grade else "rejected",
                score=proposal.score,
                competency_scores=proposal.competency_scores,
                evidence=SessionEvidence(
                    session_id=session_id, policy_id=row.grade_policy_id, stages=stages
                ).model_dump(mode="json"),
                reason="Automatic decision under the pinned calibrated policy",
                created_at=now,
                next_attempt_at=now + timedelta(seconds=rules.retry_seconds),
                confirmed_grade=grade.grade if grade else None,
            )
            session.add(decision)
            row.status, row.version = "completed", row.version + 1
            sample = (
                int(hashlib.sha256(session_id.encode()).hexdigest(), 16) % 100 < rules.audit_percent
            )
            state.status, state.reasons = (
                ("pending", ["quality_sample"]) if sample else ("scored", [])
            )
            session.flush()
            emit(
                session,
                request,
                session_id,
                row.version,
                "grade_decision_recorded",
                {
                    "candidate_id": UUID(row.candidate_id),
                    "session_id": UUID(session_id),
                    "decision_id": UUID(decision_id),
                    "reviewer_id": AUTOMATIC_REVIEWER,
                },
            )
            return True
    return False
