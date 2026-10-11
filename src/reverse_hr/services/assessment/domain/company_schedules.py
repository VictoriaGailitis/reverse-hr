"""Explicit subscription epochs, bounded UTC schedules, and durable dispatch intents."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.market_contracts import CompanyNoticeView, MarketReceipt, MarketRequest
from reverse_hr.protocols.market_access import Signature, respond
from reverse_hr.services.assessment.domain.assessment import AssessmentBase, ContentRevision
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PlanVersion,
    PracticalSession,
    subject_lock,
    utc,
)
from reverse_hr.services.assessment.domain.company_assignments import (
    AssignmentCommand,
    CompanyAssignment,
    assignment_event,
    permission,
)
from reverse_hr.services.assessment.domain.company_tasks import CompanyProposal, membership
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord, Outbox, enqueue

MIN_INTERVAL = 86400


class CompanySubscription(AssessmentBase):
    __tablename__ = "company_subscriptions"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    consent_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    min_interval_seconds: Mapped[int]


class CompanySchedule(AssessmentBase):
    __tablename__ = "company_schedules"
    __table_args__ = (
        UniqueConstraint("organization_id", "candidate_id", "plan_version_id", "starts_at"),
    )
    schedule_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    proposal_id: Mapped[str] = mapped_column(String(36))
    plan_version_id: Mapped[str] = mapped_column(String(36))
    subscription_version: Mapped[int]
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    interval_seconds: Mapped[int | None]
    max_occurrences: Mapped[int]
    issued_count: Mapped[int]
    expires_in_days: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]


class AssignmentOrigin(AssessmentBase):
    __tablename__ = "company_assignment_origins"
    assignment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36))
    schedule_id: Mapped[str | None] = mapped_column(String(36))
    subscription_version: Mapped[int | None]
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DeliveryLimit(AssessmentBase):
    __tablename__ = "company_delivery_limits"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    last_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CompanyJob(AssessmentBase):
    __tablename__ = "company_jobs"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(100), unique=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36))
    schedule_id: Mapped[str | None] = mapped_column(String(36))
    assignment_id: Mapped[str | None] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(24))
    status: Mapped[str] = mapped_column(String(16))
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    attempts: Mapped[int]
    error: Mapped[str | None] = mapped_column(String(32))


class CompanyNoticeSource(AssessmentBase):
    __tablename__ = "company_notice_sources"
    __table_args__ = (UniqueConstraint("assignment_id", "recipient_id", "kind"),)
    notice_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    assignment_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36))
    recipient_id: Mapped[str] = mapped_column(String(36))
    kind: Mapped[str] = mapped_column(String(24))
    category: Mapped[str] = mapped_column(String(16))
    subscription_version: Mapped[int | None]


class SubscriptionCommand(Contract):
    status: Literal["active", "declined", "cancelled"]
    consent_id: UUID | None = None
    min_interval_seconds: int = Field(default=604800, strict=True, ge=MIN_INTERVAL, le=7776000)

    @model_validator(mode="after")
    def consent(self):
        if (self.status == "active") != (self.consent_id is not None):
            raise ValueError("Only explicit active subscriptions carry consent")
        return self


class SubscriptionView(SubscriptionCommand):
    organization_id: UUID
    version: int


class ScheduleCommand(AssignmentCommand):
    starts_at: datetime
    interval_seconds: int | None = Field(default=None, strict=True, ge=MIN_INTERVAL, le=7776000)
    max_occurrences: int = Field(default=1, strict=True, ge=1, le=52)

    @model_validator(mode="after")
    def bounded(self):
        if self.starts_at.tzinfo is None or (
            self.interval_seconds is None and self.max_occurrences != 1
        ):
            raise ValueError("Timezone and bounded recurring occurrences required")
        self.starts_at = self.starts_at.astimezone(UTC)
        return self


class ScheduleView(ScheduleCommand):
    schedule_id: UUID
    status: Literal["active", "cancelled", "completed"]
    issued_count: int
    subscription_version: int
    version: int


class JobView(Contract):
    job_id: UUID
    kind: str
    status: Literal["pending", "done", "cancelled"]
    attempts: int
    next_at: datetime
    error: Literal["permission_unavailable", "evidence_pending", "rate_limited"] | None


router = APIRouter(tags=["company-schedules"])


def subscription_permission(request, row):
    if row is None or row.status != "active" or not row.consent_id:
        raise HTTPException(409, "Active company task subscription required")
    request.app.state.market_access.require(
        "privacy",
        "purpose-permission",
        candidate_id=UUID(row.candidate_id),
        consent_id=UUID(row.consent_id),
        consent_purpose="company_task_subscription",
    )


def subscription_view(row, organization_id):
    return SubscriptionView(
        organization_id=organization_id,
        status=row.status if row else "cancelled",
        consent_id=row.consent_id if row else None,
        min_interval_seconds=row.min_interval_seconds if row else 604800,
        version=row.version if row else 1,
    ).model_dump(mode="json")


def cancel_epoch(session, request, candidate, organization):
    schedules = list(
        session.scalars(
            select(CompanySchedule)
            .where(
                CompanySchedule.candidate_id == str(candidate),
                CompanySchedule.organization_id == str(organization),
                CompanySchedule.status == "active",
            )
            .with_for_update()
        )
    )
    for row in schedules:
        row.status, row.version = "cancelled", row.version + 1
    for job in session.scalars(
        select(CompanyJob).where(
            CompanyJob.candidate_id == str(candidate),
            CompanyJob.organization_id == str(organization),
            CompanyJob.status == "pending",
        )
    ):
        origin = session.get(AssignmentOrigin, job.assignment_id) if job.assignment_id else None
        if job.kind == "assign" or job.kind == "new_assignment" or (origin and origin.schedule_id):
            assignment = (
                session.get(CompanyAssignment, job.assignment_id) if job.assignment_id else None
            )
            if assignment and assignment.status != "assigned" and job.kind != "new_assignment":
                continue  # Subscription opt-out does not cancel an accepted practical session.
            job.status = "cancelled"
    for origin in session.scalars(
        select(AssignmentOrigin).where(
            AssignmentOrigin.candidate_id == str(candidate),
            AssignmentOrigin.organization_id == str(organization),
            AssignmentOrigin.schedule_id.is_not(None),
        )
    ):
        assignment = session.get(CompanyAssignment, origin.assignment_id)
        if assignment and assignment.status == "assigned":
            assignment.status, assignment.version = "revoked", assignment.version + 1
            assignment_event(session, request, assignment)


@router.get("/v1/company-task-subscriptions", response_model=list[SubscriptionView])
def list_subscriptions(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("candidate")
    with Session(request.app.state.engine) as session:
        query = select(CompanySubscription.organization_id).where(
            CompanySubscription.candidate_id == str(actor.subject)
        )
        if after:
            query = query.where(CompanySubscription.organization_id > str(after))
        ids = list(session.scalars(query.order_by(CompanySubscription.organization_id).limit(50)))
    return [get_subscription(request, actor, UUID(key)) for key in ids]


@router.get("/v1/company-task-subscriptions/{organization_id}", response_model=SubscriptionView)
def get_subscription(request: Request, actor: Actor, organization_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(CompanySubscription, (str(actor.subject), str(organization_id)))
        result = subscription_view(row, organization_id)
        if row and row.status == "active":
            try:
                subscription_permission(request, row)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                result["status"], result["consent_id"] = "cancelled", None
        return result


@router.put("/v1/company-task-subscriptions/{organization_id}", response_model=SubscriptionView)
def set_subscription(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    body: SubscriptionCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def guard(session):
        subject_lock(session, actor.subject)
        if body.status == "active":
            request.app.state.market_access.require(
                "privacy",
                "purpose-permission",
                candidate_id=actor.subject,
                consent_id=body.consent_id,
                consent_purpose="company_task_subscription",
            )

    def change(session):
        row = session.get(CompanySubscription, (str(actor.subject), str(organization_id)))
        if (row.version if row else 1) != expected:
            raise HTTPException(409)
        # Every edit starts a new epoch. Old schedules cannot restart after re-subscription.
        cancel_epoch(session, request, actor.subject, organization_id)
        if row is None:
            row = CompanySubscription(
                candidate_id=str(actor.subject), organization_id=str(organization_id)
            )
            session.add(row)
        row.status, row.consent_id = body.status, str(body.consent_id) if body.consent_id else None
        row.min_interval_seconds, row.version = body.min_interval_seconds, expected + 1
        return {"organization_id": str(organization_id)}

    def present(session, _):
        return subscription_view(
            session.get(CompanySubscription, (str(actor.subject), str(organization_id))),
            organization_id,
        )

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_subscription:{organization_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": expected},
        change,
        guard=guard,
        present=present,
    )


def schedule_view(row):
    return ScheduleView(
        schedule_id=row.schedule_id,
        organization_id=row.organization_id,
        candidate_id=row.candidate_id,
        proposal_id=row.proposal_id,
        plan_version_id=row.plan_version_id,
        starts_at=utc(row.starts_at),
        interval_seconds=row.interval_seconds,
        max_occurrences=row.max_occurrences,
        expires_in_days=row.expires_in_days,
        status=row.status,
        issued_count=row.issued_count,
        subscription_version=row.subscription_version,
        version=row.version,
    ).model_dump(mode="json")


def schedule_access(request, actor, session, row):
    if row is None:
        raise HTTPException(404)
    if row.candidate_id == str(actor.subject):
        actor.require("candidate")
    else:
        membership(request, actor, row.organization_id)
    for subject in sorted({row.candidate_id, row.created_by, str(actor.subject)}):
        subject_lock(session, subject)
        request.app.state.processing_access.check(UUID(subject))


@router.post("/v1/company-task-schedules", response_model=ScheduleView, status_code=201)
def create_schedule(request: Request, actor: Actor, body: ScheduleCommand, idempotency: CommandKey):
    def guard(session):
        membership(request, actor, body.organization_id)
        for subject in sorted({str(actor.subject), str(body.candidate_id)}):
            subject_lock(session, subject)
            request.app.state.processing_access.check(UUID(subject))
        subscription_permission(
            request,
            session.get(CompanySubscription, (str(body.candidate_id), str(body.organization_id))),
        )

    def change(session):
        now = datetime.now(UTC)
        if body.starts_at < now - timedelta(minutes=1) or body.starts_at > now + timedelta(
            days=365
        ):
            raise HTTPException(422)
        proposal = session.get(CompanyProposal, str(body.proposal_id))
        plan = session.get(PlanVersion, str(body.plan_version_id))
        revision = (
            session.get(ContentRevision, proposal.revision_id)
            if proposal and proposal.revision_id
            else None
        )
        if (
            not proposal
            or proposal.organization_id != str(body.organization_id)
            or proposal.status != "approved"
            or not plan
            or plan.status != "published"
            or plan.revision_ids != [proposal.revision_id]
            or not revision
            or revision.status != "published"
        ):
            raise HTTPException(409)
        sub = session.get(CompanySubscription, (str(body.candidate_id), str(body.organization_id)))
        if body.interval_seconds and body.interval_seconds < sub.min_interval_seconds:
            raise HTTPException(409, "Schedule interval violates candidate frequency preference")
        row = CompanySchedule(
            schedule_id=str(uuid4()),
            organization_id=str(body.organization_id),
            candidate_id=str(body.candidate_id),
            created_by=str(actor.subject),
            proposal_id=str(body.proposal_id),
            plan_version_id=str(body.plan_version_id),
            subscription_version=sub.version,
            starts_at=body.starts_at,
            interval_seconds=body.interval_seconds,
            max_occurrences=body.max_occurrences,
            expires_in_days=body.expires_in_days,
            issued_count=0,
            status="active",
            version=1,
        )
        session.add(row)
        add_job(session, row, "assign", body.starts_at, schedule_id=row.schedule_id)
        return {"schedule_id": row.schedule_id}

    def present(session, result):
        row = session.get(CompanySchedule, result["schedule_id"])
        schedule_access(request, actor, session, row)
        return schedule_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "company_schedule",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


@router.get("/v1/company-task-schedules", response_model=list[ScheduleView])
def list_schedules(
    request: Request, actor: Actor, organization_id: UUID | None = None, after: UUID | None = None
):
    if organization_id:
        membership(request, actor, organization_id)
    else:
        actor.require("candidate")
    with Session(request.app.state.engine) as session:
        query = select(CompanySchedule.schedule_id).where(
            CompanySchedule.organization_id == str(organization_id)
            if organization_id
            else CompanySchedule.candidate_id == str(actor.subject)
        )
        if after:
            query = query.where(CompanySchedule.schedule_id > str(after))
        ids = list(session.scalars(query.order_by(CompanySchedule.schedule_id).limit(50)))
    results = []
    for key in ids:
        try:
            results.append(get_schedule(request, actor, UUID(key)))
        except HTTPException as exc:
            if exc.status_code not in {404, 409}:
                raise
    return results


@router.get("/v1/company-task-schedules/{schedule_id}", response_model=ScheduleView)
def get_schedule(request: Request, actor: Actor, schedule_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(CompanySchedule, str(schedule_id))
        schedule_access(request, actor, session, row)
        return schedule_view(row)


@router.post("/v1/company-task-schedules/{schedule_id}/cancel", response_model=ScheduleView)
def cancel_schedule(
    request: Request,
    actor: Actor,
    schedule_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    expected = int(if_match.strip('"'))

    def guard(session):
        schedule_access(request, actor, session, session.get(CompanySchedule, str(schedule_id)))

    def change(session):
        row = session.get(CompanySchedule, str(schedule_id))
        if row.status != "active" or row.version != expected:
            raise HTTPException(409)
        row.status, row.version = "cancelled", expected + 1
        for job in session.scalars(
            select(CompanyJob).where(
                CompanyJob.schedule_id == str(schedule_id), CompanyJob.kind == "assign"
            )
        ):
            job.status = "cancelled"
        return {"schedule_id": row.schedule_id}

    def present(session, _):
        row = session.get(CompanySchedule, str(schedule_id))
        schedule_access(request, actor, session, row)
        return schedule_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_schedule_cancel:{schedule_id}",
        idempotency,
        {"version": expected},
        change,
        guard=guard,
        present=present,
    )


@router.get("/v1/company-task-schedules/{schedule_id}/jobs", response_model=list[JobView])
def jobs(request: Request, actor: Actor, schedule_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        schedule_access(request, actor, session, session.get(CompanySchedule, str(schedule_id)))
        return [
            JobView(
                job_id=j.job_id,
                kind=j.kind,
                status=j.status,
                attempts=j.attempts,
                next_at=utc(j.next_at),
                error=j.error,
            )
            for j in session.scalars(
                select(CompanyJob)
                .where(CompanyJob.schedule_id == str(schedule_id))
                .order_by(CompanyJob.job_id)
                .limit(50)
            )
        ]


def add_job(session, owner, kind, next_at, *, schedule_id=None, assignment_id=None):
    key = f"{kind}:{schedule_id if kind == 'assign' else assignment_id}"
    existing = session.scalar(select(CompanyJob).where(CompanyJob.dedupe_key == key))
    if existing:
        return existing
    job = CompanyJob(
        job_id=str(uuid4()),
        dedupe_key=key,
        candidate_id=owner.candidate_id,
        organization_id=owner.organization_id,
        created_by=owner.created_by,
        schedule_id=schedule_id,
        assignment_id=assignment_id,
        kind=kind,
        status="pending",
        next_at=next_at,
        attempts=0,
    )
    session.add(job)
    return job


class FrequencyWait(HTTPException):
    def __init__(self, next_at):
        super().__init__(409, "Company task frequency limit reached")
        self.next_at = next_at


def record_assignment(session, request, row, now):
    sub = session.get(CompanySubscription, (row.candidate_id, row.organization_id))
    limit = session.get(DeliveryLimit, (row.candidate_id, row.organization_id))
    interval = max(
        MIN_INTERVAL, sub.min_interval_seconds if sub and sub.status == "active" else MIN_INTERVAL
    )
    if limit and utc(limit.last_at) + timedelta(seconds=interval) > now:
        raise FrequencyWait(utc(limit.last_at) + timedelta(seconds=interval))
    if limit:
        limit.last_at = now
    else:
        session.add(
            DeliveryLimit(
                candidate_id=row.candidate_id, organization_id=row.organization_id, last_at=now
            )
        )
    origin = AssignmentOrigin(
        assignment_id=row.assignment_id,
        candidate_id=row.candidate_id,
        organization_id=row.organization_id,
        created_by=row.created_by,
        issued_at=now,
        subscription_version=sub.version if sub and sub.status == "active" else None,
    )
    session.add(origin)
    add_job(
        session,
        row,
        "deadline_reminder",
        max(now, utc(row.expires_at) - timedelta(days=1)),
        assignment_id=row.assignment_id,
    )
    if origin.subscription_version is not None:
        add_job(session, row, "new_assignment", now, assignment_id=row.assignment_id)


def queue_result(session, practical):
    row = session.scalar(
        select(CompanyAssignment).where(CompanyAssignment.session_id == practical.session_id)
    )
    if row:
        add_job(session, row, "result_ready", datetime.now(UTC), assignment_id=row.assignment_id)


def emit_notice(session, request, row, kind, recipient):
    existing = session.scalar(
        select(CompanyNoticeSource).where(
            CompanyNoticeSource.assignment_id == row.assignment_id,
            CompanyNoticeSource.kind == kind,
            CompanyNoticeSource.recipient_id == str(recipient),
        )
    )
    if existing:
        return existing
    origin = session.get(AssignmentOrigin, row.assignment_id)
    notice = CompanyNoticeSource(
        notice_id=str(uuid4()),
        assignment_id=row.assignment_id,
        candidate_id=row.candidate_id,
        organization_id=row.organization_id,
        created_by=row.created_by,
        recipient_id=str(recipient),
        kind=kind,
        category="marketing" if kind == "new_assignment" else "service",
        subscription_version=origin.subscription_version
        if kind == "new_assignment" and origin
        else None,
    )
    session.add(notice)
    enqueue(
        session,
        EventEnvelope(
            event_type="assessment.company_notification_requested.v1",
            producer="assessment",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(notice.notice_id),
            aggregate_version=1,
            payload={
                "notice_id": UUID(notice.notice_id),
                "assignment_id": UUID(row.assignment_id),
                "candidate_id": UUID(row.candidate_id),
                "recipient_id": UUID(recipient),
                "organization_id": UUID(row.organization_id),
                "creator_id": UUID(row.created_by),
            },
        ),
    )
    return notice


def notice_available(session, request, notice):
    row = session.get(CompanyAssignment, notice.assignment_id)
    if not row or row.status not in {"assigned", "accepted", "completed"}:
        return False
    for owner in sorted({row.candidate_id, row.created_by, notice.recipient_id}):
        if subject_lock(session, owner, allow_blocked=True).blocked:
            return False
        request.app.state.processing_access.check(UUID(owner))
    request.app.state.market_access.require(
        "employer",
        "content-membership",
        candidate_id=UUID(row.created_by),
        actor_id=UUID(row.created_by),
        organization_id=UUID(row.organization_id),
    )
    origin = session.get(AssignmentOrigin, row.assignment_id)
    if notice.kind == "new_assignment" or (
        origin and origin.schedule_id and row.status == "assigned"
    ):
        sub = session.get(CompanySubscription, (row.candidate_id, row.organization_id))
        if sub is None or sub.version != (
            notice.subscription_version
            if notice.kind == "new_assignment"
            else origin.subscription_version
        ):
            return False
        subscription_permission(request, sub)
    if notice.kind in {"new_assignment", "deadline_reminder"}:
        return row.status == "assigned" and utc(row.expires_at) > datetime.now(UTC)
    practical = session.get(PracticalSession, row.session_id) if row.session_id else None
    if not practical or practical.status not in {"submitted", "completed"}:
        return False
    request.app.state.processing_access.check_assessment(
        UUID(row.candidate_id), UUID(practical.consent_id)
    )
    if notice.recipient_id != row.candidate_id:
        permission(request, row)
    return True


@router.post("/internal/v1/market/company-notice", response_model=MarketReceipt)
def company_notice(request: Request, body: MarketRequest, signature: Signature = None):
    # Scores fetch calls back into Assessment. Authenticate first and collect outside
    # the transaction used by respond() to avoid cross-service/database deadlocks.
    ready = True
    from reverse_hr.protocols.market_access import context
    from reverse_hr.shared.event_transport import Signatures
    from reverse_hr.shared.signing import fresh, verify

    if (
        signature is None
        or body.requester != "notification"
        or body.purpose != "company-notice"
        or not fresh(body.issued_at)
    ):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "assessment_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
        verify(
            signatures,
            "notification",
            signature,
            context("assessment", "company-notice", "request"),
            body,
        )
    except Exception as exc:
        raise HTTPException(401) from exc
    with Session(request.app.state.engine) as session:
        source = session.get(CompanyNoticeSource, str(body.notice_id))
        assignment = (
            session.get(CompanyAssignment, source.assignment_id)
            if source and source.recipient_id == str(body.candidate_id)
            else None
        )
        practical = (
            session.get(PracticalSession, assignment.session_id)
            if assignment and assignment.session_id
            else None
        )
        requires_scores = bool(source and assignment and source.kind == "result_ready")
        if practical:
            session.expunge(practical)
    if requires_scores:
        ready = False
        if practical and practical.status in {"submitted", "completed"}:
            from reverse_hr.services.assessment.domain.assessment_grades import gather

            try:
                scores = gather(request, practical)
                ready = bool(
                    scores and all(s.review_id is not None and s.score is not None for s in scores)
                )
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise

    def check(session):
        row = session.get(CompanyNoticeSource, str(body.notice_id))
        if row is None or row.recipient_id != str(body.candidate_id) or not ready:
            return None, 0
        try:
            if not notice_available(session, request, row):
                return None, 1
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            return None, 1
        return CompanyNoticeView(
            notice_id=row.notice_id,
            assignment_id=row.assignment_id,
            organization_id=row.organization_id,
            candidate_id=row.candidate_id,
            creator_id=row.created_by,
            author_id=row.created_by,
            recipient_id=row.recipient_id,
            kind=row.kind,
            category=row.category,
        ).model_dump(mode="json"), 1

    return respond(
        request,
        body,
        signature,
        "assessment",
        "company-notice",
        MaterialNonce,
        {"notification"},
        check,
    )


def purge(session, subject):
    for model in (CompanyJob, CompanyNoticeSource, AssignmentOrigin, CompanySchedule):
        refs = list(
            session.scalars(
                select(model).where((model.candidate_id == subject) | (model.created_by == subject))
            )
        )
        for row in refs:
            for key in (getattr(row, "schedule_id", None), getattr(row, "notice_id", None)):
                if key:
                    session.execute(
                        delete(IdempotencyRecord).where(
                            IdempotencyRecord.response.contains(key)
                            | IdempotencyRecord.operation.contains(key)
                        )
                    )
                    session.execute(
                        delete(Outbox).where(Outbox.envelope["aggregate_id"].as_string() == key)
                    )
            session.delete(row)
    session.execute(delete(CompanySubscription).where(CompanySubscription.candidate_id == subject))
    session.execute(delete(DeliveryLimit).where(DeliveryLimit.candidate_id == subject))
