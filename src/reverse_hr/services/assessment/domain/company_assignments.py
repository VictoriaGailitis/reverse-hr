"""Company assignments reuse pinned practical sessions without awarding a general grade."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import DateTime, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.services.assessment.domain.assessment import AssessmentBase, ContentRevision
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PlanVersion,
    PracticalSession,
    SessionCommand,
    SessionView,
    admit_session,
    emit,
    guard_session_admission,
    session_view,
    subject_lock,
    utc,
)
from reverse_hr.services.assessment.domain.company_tasks import CompanyProposal, membership
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord, Outbox


class CompanyAssignment(AssessmentBase):
    __tablename__ = "company_assignments"
    assignment_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    proposal_id: Mapped[str] = mapped_column(String(36))
    plan_version_id: Mapped[str] = mapped_column(String(36))
    session_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    result_grant_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AssignmentCommand(Contract):
    organization_id: UUID
    candidate_id: UUID
    proposal_id: UUID
    plan_version_id: UUID
    expires_in_days: int = Field(default=14, strict=True, ge=1, le=90)


class AssignmentView(Contract):
    assignment_id: UUID
    organization_id: UUID
    candidate_id: UUID
    proposal_id: UUID
    plan_version_id: UUID
    session_id: UUID | None
    status: Literal[
        "assigned",
        "accepted",
        "declined",
        "revoked",
        "expired",
        "cancelled",
        "in_progress",
        "submitted",
        "completed",
    ]
    version: int
    expires_at: datetime
    formats: list[Literal["code", "sql", "voice", "vcv", "whiteboard"]]
    duration_seconds: int
    result_recipient: UUID
    result_scope: Literal["reviewed_scores_only"] = "reviewed_scores_only"
    affects_general_grade: Literal[False] = False
    reveals_contacts: Literal[False] = False


class Acceptance(Contract):
    assessment_consent_id: UUID
    result_grant_id: UUID


class ResultCriterion(Contract):
    criterion_key: str
    competency: str
    points: int = Field(ge=0, le=100)
    max_points: int = Field(ge=1, le=100)


class ResultStage(Contract):
    stage_id: UUID
    format: Literal["code", "sql", "voice", "vcv", "whiteboard"]
    score: int = Field(ge=0, le=100)
    review_id: UUID
    criteria: list[ResultCriterion]


class AssignmentResult(Contract):
    assignment_id: UUID
    session_id: UUID
    organization_id: UUID
    status: Literal["review_pending", "reviewed"]
    stages: list[ResultStage]
    affects_general_grade: Literal[False] = False


router = APIRouter(prefix="/v1/company-assignments", tags=["company-assignments"])


def authorize(request, actor, session, assignment_id, *, employer=False, admission=False):
    row = session.get(CompanyAssignment, str(assignment_id))
    if row is None:
        raise HTTPException(404)
    if employer:
        membership(request, actor, row.organization_id)
    else:
        actor.require("candidate")
        if row.candidate_id != str(actor.subject):
            raise HTTPException(404)
    owners = {row.candidate_id, row.created_by, str(actor.subject)}
    if admission:
        from reverse_hr.contracts.session_test_pins import stored_pins
        from reverse_hr.services.assessment.domain.assessment_plan_tests import owner_ids

        plan = session.get(PlanVersion, row.plan_version_id)
        if plan is None:
            raise HTTPException(409)
        try:
            owners |= owner_ids(session, actor.subject, stored_pins(plan))
        except ValueError as exc:
            raise HTTPException(409, "Corrupted plan pins") from exc
    # Acquire the union before any admission helper repeats locks on suite owners.
    for owner in sorted(owners):
        subject_lock(session, owner)
        request.app.state.processing_access.check(UUID(owner))
    row = session.scalar(
        select(CompanyAssignment)
        .where(CompanyAssignment.assignment_id == str(assignment_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return row


def permission(request, row, grant_id=None):
    if not (grant_id or row.result_grant_id):
        raise HTTPException(409)
    request.app.state.market_access.require(
        "privacy",
        "company-result-permission",
        candidate_id=UUID(row.candidate_id),
        organization_id=UUID(row.organization_id),
        assignment_id=UUID(row.assignment_id),
        result_grant_id=UUID(str(grant_id or row.result_grant_id)),
    )


def view(session, row):
    plan = session.get(PlanVersion, row.plan_version_id)
    status = row.status
    practical = session.get(PracticalSession, row.session_id) if row.session_id else None
    if status == "assigned" and utc(row.expires_at) <= datetime.now(UTC):
        status = "expired"
    elif status == "accepted" and practical:
        status = "accepted" if practical.status == "preflight" else practical.status
    return AssignmentView(
        assignment_id=row.assignment_id,
        organization_id=row.organization_id,
        candidate_id=row.candidate_id,
        proposal_id=row.proposal_id,
        plan_version_id=row.plan_version_id,
        session_id=row.session_id,
        status=status,
        version=row.version,
        expires_at=utc(row.expires_at),
        formats=[s["format"] for s in plan.stages],
        duration_seconds=plan.duration_seconds,
        result_recipient=row.organization_id,
    ).model_dump(mode="json")


def assignment_event(session, request, row):
    emit(
        session,
        request,
        row.assignment_id,
        row.version,
        "company_assignment_changed",
        {
            "assignment_id": UUID(row.assignment_id),
            "candidate_id": UUID(row.candidate_id),
            "organization_id": UUID(row.organization_id),
        },
    )


def create_assignment(session, request, actor, body, *, now=None):
    now = now or datetime.now(UTC)
    proposal = session.get(CompanyProposal, str(body.proposal_id))
    plan = session.get(PlanVersion, str(body.plan_version_id))
    if (
        not proposal
        or proposal.organization_id != str(body.organization_id)
        or proposal.status != "approved"
        or not plan
        or plan.status != "published"
        or plan.revision_ids != [proposal.revision_id]
    ):
        raise HTTPException(409)
    revision = session.get(ContentRevision, proposal.revision_id)
    if not revision or revision.status != "published":
        raise HTTPException(409)
    if session.scalar(
        select(CompanyAssignment.assignment_id)
        .where(
            CompanyAssignment.organization_id == str(body.organization_id),
            CompanyAssignment.candidate_id == str(body.candidate_id),
            CompanyAssignment.plan_version_id == str(body.plan_version_id),
            CompanyAssignment.status.in_(["assigned", "accepted"]),
            CompanyAssignment.expires_at > now,
        )
        .limit(1)
    ):
        raise HTTPException(409)
    row = CompanyAssignment(
        assignment_id=str(uuid4()),
        organization_id=str(body.organization_id),
        candidate_id=str(body.candidate_id),
        created_by=str(actor.subject),
        proposal_id=str(body.proposal_id),
        plan_version_id=str(body.plan_version_id),
        status="assigned",
        version=1,
        expires_at=now + timedelta(days=body.expires_in_days),
    )
    session.add(row)
    from reverse_hr.services.assessment.domain.company_schedules import record_assignment

    record_assignment(session, request, row, now)
    assignment_event(session, request, row)
    return {"assignment_id": row.assignment_id}


@router.post("", response_model=AssignmentView, status_code=201)
def assign(request: Request, actor: Actor, body: AssignmentCommand, idempotency: CommandKey):
    def guard(session):
        membership(request, actor, body.organization_id)
        for owner in sorted({str(actor.subject), str(body.candidate_id)}):
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))

    def change(session):
        return create_assignment(session, request, actor, body)

    def present(session, result):
        return view(
            session, authorize(request, actor, session, result["assignment_id"], employer=True)
        )

    return execute(
        request.app.state.engine,
        actor.subject,
        "company_assignment",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


@router.get("/{assignment_id}", response_model=AssignmentView)
def get_assignment(request: Request, actor: Actor, assignment_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(CompanyAssignment, str(assignment_id))
        if row is None:
            raise HTTPException(404)
        return view(
            session,
            authorize(
                request,
                actor,
                session,
                assignment_id,
                employer=row.candidate_id != str(actor.subject),
            ),
        )


@router.post("/{assignment_id}/accept", response_model=SessionView, status_code=201)
def accept(
    request: Request,
    actor: Actor,
    assignment_id: UUID,
    body: Acceptance,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    expected = int(if_match.strip('"'))

    def guard(session):
        row = authorize(request, actor, session, assignment_id, admission=True)
        if row.status == "assigned":
            from reverse_hr.services.assessment.domain.company_schedules import (
                AssignmentOrigin,
                CompanySubscription,
                subscription_permission,
            )

            origin = session.get(AssignmentOrigin, row.assignment_id)
            if origin and origin.schedule_id:
                sub = session.get(CompanySubscription, (row.candidate_id, row.organization_id))
                if not sub or sub.version != origin.subscription_version:
                    raise HTTPException(409)
                subscription_permission(request, sub)
        permission(request, row, body.result_grant_id)
        guard_session_admission(
            request,
            actor,
            SessionCommand(
                plan_version_id=row.plan_version_id,
                assessment_consent_id=body.assessment_consent_id,
            ),
            session,
            assignment_id=row.assignment_id,
        )

    def change(session):
        row = session.get(CompanyAssignment, str(assignment_id))
        proposal = session.get(CompanyProposal, row.proposal_id)
        if (
            row.version != expected
            or row.status != "assigned"
            or utc(row.expires_at) <= datetime.now(UTC)
            or not proposal
            or proposal.status != "approved"
        ):
            raise HTTPException(409)
        result = admit_session(
            request,
            actor,
            SessionCommand(
                plan_version_id=row.plan_version_id,
                assessment_consent_id=body.assessment_consent_id,
            ),
            session,
        )
        row.session_id, row.result_grant_id = result["session_id"], str(body.result_grant_id)
        row.status, row.version = "accepted", expected + 1
        assignment_event(session, request, row)
        return {"session_id": row.session_id}

    def present(session, result):
        row = authorize(request, actor, session, assignment_id)
        practical = session.get(PracticalSession, result["session_id"])
        if practical is None or row.session_id != practical.session_id:
            raise HTTPException(404)
        return session_view(practical)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_accept:{assignment_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": expected},
        change,
        201,
        guard=guard,
        present=present,
    )


def close(request, actor, assignment_id, idempotency, if_match, *, employer):
    expected = int(if_match.strip('"'))

    def guard(session):
        authorize(request, actor, session, assignment_id, employer=employer)

    def change(session):
        row = session.get(CompanyAssignment, str(assignment_id))
        if row.version != expected or row.status != "assigned":
            raise HTTPException(409)
        row.status, row.version = ("revoked" if employer else "declined"), expected + 1
        assignment_event(session, request, row)
        return {"assignment_id": row.assignment_id}

    def present(session, result):
        return view(session, authorize(request, actor, session, assignment_id, employer=employer))

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_{'revoke' if employer else 'decline'}:{assignment_id}",
        idempotency,
        {"version": expected},
        change,
        guard=guard,
        present=present,
    )


@router.post("/{assignment_id}/decline", response_model=AssignmentView)
def decline(
    request: Request,
    actor: Actor,
    assignment_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return close(request, actor, assignment_id, idempotency, if_match, employer=False)


@router.post("/{assignment_id}/revoke", response_model=AssignmentView)
def revoke(
    request: Request,
    actor: Actor,
    assignment_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return close(request, actor, assignment_id, idempotency, if_match, employer=True)


@router.get("/{assignment_id}/result", response_model=AssignmentResult)
def result(request: Request, actor: Actor, assignment_id: UUID):
    def guard(session):
        row = session.get(CompanyAssignment, str(assignment_id))
        if row is None:
            raise HTTPException(404)
        company = row.candidate_id != str(actor.subject)
        row = authorize(request, actor, session, assignment_id, employer=company)
        if company:
            permission(request, row)
        practical = session.get(PracticalSession, row.session_id) if row.session_id else None
        if (
            row.status not in {"accepted", "completed"}
            or not practical
            or practical.status not in {"submitted", "completed"}
            or practical.grade_policy_id
        ):
            raise HTTPException(409)
        request.app.state.processing_access.check_assessment(
            UUID(row.candidate_id), UUID(practical.consent_id)
        )
        return row, practical

    with Session(request.app.state.engine) as session, session.begin():
        row, practical = guard(session)
        refs = row.session_id, row.organization_id
        session.expunge(practical)
    from reverse_hr.services.assessment.domain.assessment_grades import gather

    scores = gather(request, practical)
    ready = all(s.review_id is not None and s.score is not None for s in scores)
    with Session(request.app.state.engine) as session, session.begin():
        row, practical = guard(session)
        if refs != (row.session_id, row.organization_id):
            raise HTTPException(409)
        return AssignmentResult(
            assignment_id=assignment_id,
            session_id=row.session_id,
            organization_id=row.organization_id,
            status="reviewed" if ready else "review_pending",
            stages=[
                ResultStage(
                    stage_id=spec["stage_id"],
                    format=spec["format"],
                    score=s.score,
                    review_id=s.review_id,
                    criteria=[
                        ResultCriterion(
                            criterion_key=c.criterion_key,
                            competency=c.competency,
                            max_points=c.max_points,
                            points=c.points,
                        )
                        for c in s.criteria
                    ],
                )
                for spec, s in zip(practical.stages, scores, strict=True)
            ]
            if ready
            else [],
        )


@router.post("/{assignment_id}/complete", response_model=AssignmentView)
def complete(
    request: Request,
    actor: Actor,
    assignment_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))
    reviewed = result(request, actor, assignment_id)
    if reviewed.status != "reviewed":
        raise HTTPException(409, "All stages require human-reviewed evidence")

    def guard(session):
        row = authorize(request, actor, session, assignment_id)
        practical = session.get(PracticalSession, row.session_id) if row.session_id else None
        if (
            practical is None
            or row.session_id != str(reviewed.session_id)
            or practical.grade_policy_id
        ):
            raise HTTPException(409)
        request.app.state.processing_access.check_assessment(
            actor.subject, UUID(practical.consent_id)
        )

    def change(session):
        row = session.get(CompanyAssignment, str(assignment_id))
        practical = session.get(PracticalSession, row.session_id)
        if row.status != "accepted" or row.version != expected or practical.status != "submitted":
            raise HTTPException(409)
        row.status, row.version = "completed", expected + 1
        practical.status, practical.version = "completed", practical.version + 1
        assignment_event(session, request, row)
        return {"assignment_id": row.assignment_id}

    def present(session, response):
        return view(session, authorize(request, actor, session, assignment_id))

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_complete:{assignment_id}",
        idempotency,
        {"version": expected},
        change,
        guard=guard,
        present=present,
    )


@router.get("", response_model=list[AssignmentView])
def list_assignments(
    request: Request,
    actor: Actor,
    organization_id: UUID | None = None,
    after: UUID | None = None,
):
    with Session(request.app.state.engine) as session:
        if organization_id:
            membership(request, actor, organization_id)
            query = select(CompanyAssignment).where(
                CompanyAssignment.organization_id == str(organization_id)
            )
        else:
            actor.require("candidate")
            query = select(CompanyAssignment).where(
                CompanyAssignment.candidate_id == str(actor.subject)
            )
        if after:
            query = query.where(CompanyAssignment.assignment_id > str(after))
        ids = list(
            session.scalars(
                query.with_only_columns(CompanyAssignment.assignment_id)
                .order_by(CompanyAssignment.assignment_id)
                .limit(50)
            )
        )
    results = []
    for key in ids:
        with Session(request.app.state.engine) as session, session.begin():
            try:
                results.append(
                    view(
                        session,
                        authorize(request, actor, session, key, employer=bool(organization_id)),
                    )
                )
            except HTTPException as exc:
                if exc.status_code not in {404, 409}:
                    raise
    return results


def purge(session, subject):
    from reverse_hr.services.assessment.domain.company_schedules import purge as purge_schedules

    purge_schedules(session, subject)
    ids = list(
        session.scalars(
            select(CompanyAssignment.assignment_id).where(
                (CompanyAssignment.candidate_id == subject)
                | (CompanyAssignment.created_by == subject)
            )
        )
    )
    for key in ids:
        session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.operation.in_(
                    [
                        f"company_accept:{key}",
                        f"company_decline:{key}",
                        f"company_revoke:{key}",
                        f"company_complete:{key}",
                    ]
                )
                | IdempotencyRecord.response.contains(key)
            )
        )
    session.execute(delete(Outbox).where(Outbox.envelope["aggregate_id"].as_string().in_(ids)))
    # Preserve the immutable recipient binding of another candidate's session.
    # Its erased author is restricted; no employer export can pass authorize().
    session.execute(delete(CompanyAssignment).where(CompanyAssignment.candidate_id == subject))
