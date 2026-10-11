"""SQL durable dispatch: external reads first, then subject fences and one atomic commit."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.services.assessment.domain.assessment_sessions import (
    PracticalSession,
    subject_lock,
    utc,
)
from reverse_hr.services.assessment.domain.company_assignments import (
    AssignmentCommand,
    CompanyAssignment,
    create_assignment,
)
from reverse_hr.services.assessment.domain.company_schedules import (
    AssignmentOrigin,
    CompanyJob,
    CompanySchedule,
    CompanySubscription,
    FrequencyWait,
    cancel_epoch,
    emit_notice,
    subscription_permission,
)


def request_context(engine, processing, market, scores):
    return SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                engine=engine,
                processing_access=processing,
                market_access=market,
                grade_access=scores,
            )
        ),
        state=SimpleNamespace(trace_id=uuid4()),
    )


def run_one(engine, processing, market, scores, *, now=None):
    now = now or datetime.now(UTC)
    request = request_context(engine, processing, market, scores)
    with Session(engine) as session:
        job = session.scalar(
            select(CompanyJob)
            .where(CompanyJob.status == "pending", CompanyJob.next_at <= now)
            .order_by(CompanyJob.next_at, CompanyJob.job_id)
            .limit(1)
        )
        if job is None:
            return False
        job_id, owners = job.job_id, sorted({job.candidate_id, job.created_by})
        assignment = (
            session.get(CompanyAssignment, job.assignment_id) if job.assignment_id else None
        )
        schedule = session.get(CompanySchedule, job.schedule_id) if job.schedule_id else None
        sub = session.get(CompanySubscription, (job.candidate_id, job.organization_id))
        origin = session.get(AssignmentOrigin, job.assignment_id) if job.assignment_id else None
        practical = (
            session.get(PracticalSession, assignment.session_id)
            if assignment and assignment.session_id
            else None
        )
        for row in (job, assignment, schedule, sub, origin, practical):
            if row is not None:
                session.expunge(row)
    error, retry_at, invalid_subscription = None, None, False
    try:
        for owner in owners:
            processing.check(UUID(owner))
        market.require(
            "employer",
            "content-membership",
            candidate_id=UUID(job.created_by),
            actor_id=UUID(job.created_by),
            organization_id=UUID(job.organization_id),
        )
        if (
            job.kind == "assign"
            or job.kind == "new_assignment"
            or (origin and origin.schedule_id and assignment and assignment.status == "assigned")
        ):
            expected_epoch = (
                schedule.subscription_version
                if job.kind == "assign" and schedule
                else origin.subscription_version
                if origin
                else None
            )
            if not sub or sub.version != expected_epoch:
                raise HTTPException(409)
            try:
                subscription_permission(request, sub)
            except HTTPException as exc:
                invalid_subscription = exc.status_code == 409
                raise
        if job.kind == "result_ready":
            if not practical or practical.status not in {"submitted", "completed"}:
                raise HTTPException(409)
            processing.check_assessment(UUID(practical.candidate_id), UUID(practical.consent_id))
            from reverse_hr.services.assessment.domain.assessment_grades import gather

            try:
                result = gather(request, practical)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                result = []
            if not result or any(s.review_id is None or s.score is None for s in result):
                error, retry_at = "evidence_pending", now + timedelta(minutes=5)
    except HTTPException as exc:
        error = "cancel" if exc.status_code in {403, 404, 409} else "permission_unavailable"
    except Exception:
        error = "permission_unavailable"
    try:
        with Session(engine) as session, session.begin():
            for owner in owners:
                state = subject_lock(session, owner, allow_blocked=True)
                if state.blocked:
                    error = "cancel"
            current = session.scalar(
                select(CompanyJob)
                .where(CompanyJob.job_id == job_id)
                .with_for_update(skip_locked=True)
                .execution_options(populate_existing=True)
            )
            if current is None or current.status != "pending" or utc(current.next_at) > now:
                return True
            current.attempts += 1
            current.error = None
            schedule = (
                session.get(CompanySchedule, current.schedule_id) if current.schedule_id else None
            )
            row = (
                session.get(CompanyAssignment, current.assignment_id)
                if current.assignment_id
                else None
            )
            origin = (
                session.get(AssignmentOrigin, current.assignment_id)
                if current.assignment_id
                else None
            )
            sub = session.get(CompanySubscription, (current.candidate_id, current.organization_id))
            if current.kind == "assign" and (
                not schedule
                or schedule.status != "active"
                or not sub
                or sub.status != "active"
                or sub.version != schedule.subscription_version
            ):
                error = "cancel"
            if current.kind == "new_assignment" and (
                not sub
                or sub.status != "active"
                or not origin
                or sub.version != origin.subscription_version
            ):
                error = "cancel"
            if current.kind != "assign" and (
                not row or row.status not in {"assigned", "accepted", "completed"}
            ):
                error = "cancel"
            if (
                origin
                and origin.schedule_id
                and row
                and row.status == "assigned"
                and (
                    not sub or sub.status != "active" or sub.version != origin.subscription_version
                )
            ):
                error = "cancel"
            if invalid_subscription:
                cancel_epoch(session, request, current.candidate_id, current.organization_id)
            if error == "cancel":
                current.status = "cancelled"
                if schedule and current.kind == "assign" and schedule.status == "active":
                    schedule.status, schedule.version = "cancelled", schedule.version + 1
                return True
            if error:
                current.error = error
                current.next_at = retry_at or now + timedelta(
                    seconds=min(3600, 5 * 2 ** min(current.attempts, 10))
                )
                return True
            # Recheck permissions under the local fences. No scores RPC under Assessment locks.
            for owner in owners:
                processing.check(UUID(owner))
            market.require(
                "employer",
                "content-membership",
                candidate_id=UUID(current.created_by),
                actor_id=UUID(current.created_by),
                organization_id=UUID(current.organization_id),
            )
            if current.kind == "assign":
                subscription_permission(request, sub)
                actor = SimpleNamespace(subject=UUID(current.created_by))
                body = AssignmentCommand(
                    organization_id=current.organization_id,
                    candidate_id=current.candidate_id,
                    proposal_id=schedule.proposal_id,
                    plan_version_id=schedule.plan_version_id,
                    expires_in_days=schedule.expires_in_days,
                )
                duplicate = session.scalar(
                    select(CompanyAssignment)
                    .where(
                        CompanyAssignment.organization_id == current.organization_id,
                        CompanyAssignment.candidate_id == current.candidate_id,
                        CompanyAssignment.plan_version_id == schedule.plan_version_id,
                        CompanyAssignment.status.in_(["assigned", "accepted"]),
                        CompanyAssignment.expires_at > now,
                    )
                    .limit(1)
                )
                if duplicate:
                    raise FrequencyWait(utc(duplicate.expires_at))
                result = create_assignment(session, request, actor, body, now=now)
                session.flush()
                origin = session.get(AssignmentOrigin, result["assignment_id"])
                origin.schedule_id = schedule.schedule_id
                for related in session.scalars(
                    select(CompanyJob).where(CompanyJob.assignment_id == result["assignment_id"])
                ):
                    related.schedule_id = schedule.schedule_id
                schedule.issued_count, schedule.version = (
                    schedule.issued_count + 1,
                    schedule.version + 1,
                )
                if schedule.interval_seconds and schedule.issued_count < schedule.max_occurrences:
                    interval = schedule.interval_seconds
                    due = utc(schedule.starts_at)
                    current.next_at = due + timedelta(
                        seconds=interval * (int((now - due).total_seconds()) // interval + 1)
                    )
                    current.error = None
                else:
                    current.status, schedule.status = "done", "completed"
                return True
            if current.kind in {"new_assignment", "deadline_reminder"}:
                if row.status != "assigned" or utc(row.expires_at) <= now:
                    current.status = "cancelled"
                    return True
                if current.kind == "new_assignment" or (origin and origin.schedule_id):
                    subscription_permission(request, sub)
                emit_notice(session, request, row, current.kind, row.candidate_id)
            else:
                practical = session.get(PracticalSession, row.session_id)
                if practical is None or practical.status not in {"submitted", "completed"}:
                    current.status = "cancelled"
                    return True
                processing.check_assessment(UUID(row.candidate_id), UUID(practical.consent_id))
                emit_notice(session, request, row, "result_ready", row.candidate_id)
                # Company disclosure has its own permission. Candidate notification is independent.
                from reverse_hr.services.assessment.domain.company_assignments import permission

                try:
                    permission(request, row)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                else:
                    emit_notice(session, request, row, "result_ready", row.created_by)
            current.status = "done"
        return True
    except FrequencyWait as exc:
        retry_at, error = exc.next_at, "rate_limited"
    except HTTPException as exc:
        retry_at, error = (
            now + timedelta(minutes=5),
            "cancel" if exc.status_code in {403, 404, 409} else "permission_unavailable",
        )
    except (OperationalError, IntegrityError):
        return False  # The transaction rolled back; another worker or next poll can recover it.
    with Session(engine) as session, session.begin():
        for owner in owners:
            subject_lock(session, owner, allow_blocked=True)
        current = session.scalar(
            select(CompanyJob).where(CompanyJob.job_id == job_id).with_for_update()
        )
        if current and current.status == "pending" and utc(current.next_at) <= now:
            current.attempts += 1
            current.error = None if error == "cancel" else error
            current.status = "cancelled" if error == "cancel" else "pending"
            current.next_at = retry_at
            if error == "cancel" and current.kind == "assign":
                schedule = session.get(CompanySchedule, current.schedule_id)
                if schedule and schedule.status == "active":
                    schedule.status, schedule.version = "cancelled", schedule.version + 1
    return True
