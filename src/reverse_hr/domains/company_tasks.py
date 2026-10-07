"""Company proposals enter the demo bank only after independent human review."""

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import IdempotencyRecord, Outbox, enqueue
from reverse_hr.domains.assessment import (
    AssessmentBase,
    ContentFamily,
    ContentPackage,
    ContentRevision,
)
from reverse_hr.domains.assessment import (
    event as content_event,
)
from reverse_hr.domains.assessment_sessions import subject_lock
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import canonical


class CompanyProposal(AssessmentBase):
    __tablename__ = "company_task_proposals"
    proposal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(36), index=True)
    review_reason: Mapped[str | None] = mapped_column(String(2000))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revision_id: Mapped[str | None] = mapped_column(String(36), unique=True)


class ProposalCommand(Contract):
    organization_id: UUID
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    content: ContentPackage


class ProposalView(ProposalCommand):
    proposal_id: UUID
    digest: str
    status: Literal["draft", "submitted", "approved", "rejected", "withdrawn"]
    version: int
    revision_id: UUID | None
    bank_status: Literal["draft", "published", "retired"] | None
    review_reason: str | None


class ProposalReview(Contract):
    outcome: Literal["approve", "reject"]
    digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class WithdrawCommand(Contract):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


router = APIRouter(prefix="/v1/company-task-proposals", tags=["company-task-proposals"])


def membership(request, actor, organization):
    actor.require("employer")
    request.app.state.market_access.require(
        "employer",
        "content-membership",
        candidate_id=actor.subject,
        actor_id=actor.subject,
        organization_id=UUID(str(organization)),
    )


def related(session, row, actor):
    revision = session.get(ContentRevision, row.revision_id) if row.revision_id else None
    if row.revision_id and revision is None:
        raise HTTPException(409)
    subjects = {str(actor.subject), row.created_by}
    if row.reviewed_by:
        subjects.add(row.reviewed_by)
    if revision and revision.retired_by:
        subjects.add(revision.retired_by)
    return subjects


def guard_proposal(request, actor, session, proposal_id, *, reviewer=False):
    row = session.get(CompanyProposal, str(proposal_id))
    if row is None:
        raise HTTPException(404)
    if reviewer:
        actor.require("content_admin", mfa=True)
        if row.status == "draft":
            raise HTTPException(409)
        if row.created_by == str(actor.subject):
            raise HTTPException(403)
    else:
        membership(request, actor, row.organization_id)
    subjects = related(session, row, actor)
    for subject in sorted(subjects):
        subject_lock(session, subject)
        request.app.state.processing_access.check(UUID(subject))
    if reviewer:
        affiliation = request.app.state.market_access.fetch(
            "employer",
            "affiliation",
            candidate_id=actor.subject,
            actor_id=actor.subject,
            organization_id=UUID(row.organization_id),
        )
        if affiliation.allowed:
            raise HTTPException(403)
    row = session.scalar(
        select(CompanyProposal)
        .where(CompanyProposal.proposal_id == str(proposal_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404)
    if not related(session, row, actor).issubset(subjects):
        raise HTTPException(409)
    return row


def proposal_view(session, row):
    session.flush()
    revision = session.get(ContentRevision, row.revision_id) if row.revision_id else None
    if revision:
        session.refresh(revision)
    return ProposalView(
        proposal_id=row.proposal_id,
        organization_id=row.organization_id,
        name=row.name,
        content=row.content,
        digest=row.digest,
        status=row.status,
        version=row.version,
        revision_id=row.revision_id,
        bank_status=revision.status if revision else None,
        review_reason=row.review_reason,
    ).model_dump(mode="json")


def set_content(row, body):
    package = body.content.model_copy(
        update={
            "source_dataset": f"company:{row.organization_id}",
            "source_version": f"proposal:{row.proposal_id}:v{row.version}",
        }
    )
    row.name, row.content = body.name, package.model_dump(mode="json")
    row.digest = hashlib.sha256(canonical(package)).hexdigest()


def emit(session, request, row, actor):
    enqueue(
        session,
        EventEnvelope(
            producer="assessment",
            event_type="assessment.company_proposal_changed.v1",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(row.proposal_id),
            aggregate_version=row.version,
            payload={
                "proposal_id": UUID(row.proposal_id),
                "organization_id": UUID(row.organization_id),
                "author_id": UUID(row.created_by),
                "actor_id": actor.subject,
            },
        ),
    )


@router.post("", response_model=ProposalView, status_code=201)
def create(request: Request, actor: Actor, body: ProposalCommand, idempotency: CommandKey):
    def guard(session):
        subject_lock(session, actor.subject)
        membership(request, actor, body.organization_id)

    def change(session):
        row = CompanyProposal(
            proposal_id=str(uuid4()),
            organization_id=str(body.organization_id),
            created_by=str(actor.subject),
            status="draft",
            version=1,
            created_at=datetime.now(UTC),
        )
        set_content(row, body)
        session.add(row)
        emit(session, request, row, actor)
        session.flush()
        return {"proposal_id": row.proposal_id}

    def present(session, result):
        row = guard_proposal(request, actor, session, result["proposal_id"])
        return proposal_view(session, row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "company_proposal_create",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


@router.get("/{proposal_id}", response_model=ProposalView)
def get_proposal(request: Request, actor: Actor, proposal_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        reviewer = "content_admin" in actor.roles and "employer" not in actor.roles
        row = guard_proposal(request, actor, session, proposal_id, reviewer=reviewer)
        return proposal_view(session, row)


@router.put("/{proposal_id}", response_model=ProposalView)
def update_proposal(
    request: Request,
    actor: Actor,
    proposal_id: UUID,
    body: ProposalCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        guard_proposal(request, actor, session, proposal_id)

    def change(session):
        row = session.get(CompanyProposal, str(proposal_id))
        if row.created_by != str(actor.subject):
            raise HTTPException(403)
        if (
            row.status != "draft"
            or row.version != int(if_match.strip('"'))
            or row.organization_id != str(body.organization_id)
        ):
            raise HTTPException(409)
        row.version += 1
        set_content(row, body)
        emit(session, request, row, actor)
        return {"proposal_id": row.proposal_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_proposal_update:{proposal_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: proposal_view(
            session, session.get(CompanyProposal, str(proposal_id))
        ),
    )


@router.post("/{proposal_id}/submit", response_model=ProposalView)
def submit(
    request: Request,
    actor: Actor,
    proposal_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        guard_proposal(request, actor, session, proposal_id)

    def change(session):
        row = session.get(CompanyProposal, str(proposal_id))
        if row.status != "draft" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.status, row.version = "submitted", row.version + 1
        emit(session, request, row, actor)
        return {"proposal_id": row.proposal_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_proposal_submit:{proposal_id}",
        idempotency,
        {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: proposal_view(
            session, session.get(CompanyProposal, str(proposal_id))
        ),
    )


@router.post("/{proposal_id}/review", response_model=ProposalView)
def review(
    request: Request,
    actor: Actor,
    proposal_id: UUID,
    body: ProposalReview,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        guard_proposal(request, actor, session, proposal_id, reviewer=True)

    def change(session):
        row = session.get(CompanyProposal, str(proposal_id))
        if (
            row.status != "submitted"
            or row.version != int(if_match.strip('"'))
            or row.digest != body.digest
        ):
            raise HTTPException(409)
        # Revalidate the exact immutable submitted package before entering the bank.
        content = ContentPackage.model_validate(row.content)
        if hashlib.sha256(canonical(content)).hexdigest() != row.digest:
            raise HTTPException(409)
        row.status = "approved" if body.outcome == "approve" else "rejected"
        row.version += 1
        row.reviewed_by, row.review_reason, row.reviewed_at = (
            str(actor.subject),
            body.reason,
            datetime.now(UTC),
        )
        if body.outcome == "approve":
            family = ContentFamily(
                family_id=str(uuid4()),
                name=row.name,
                specialization=content.specialization,
                grade=content.grade.value,
                version=1,
            )
            session.add(family)
            session.flush()
            revision = ContentRevision(
                revision_id=str(uuid4()),
                family_id=family.family_id,
                number=1,
                content=row.content,
                status="published",
                version=2,
                created_by=row.created_by,
                created_at=row.created_at,
                reviewed_by=str(actor.subject),
                review_reason=body.reason,
                published_at=row.reviewed_at,
            )
            session.add(revision)
            row.revision_id = revision.revision_id
            content_event(session, request, revision, "published")
        emit(session, request, row, actor)
        session.flush()
        return {"proposal_id": row.proposal_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_proposal_review:{proposal_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: proposal_view(
            session, session.get(CompanyProposal, str(proposal_id))
        ),
    )


@router.post("/{proposal_id}/withdraw", response_model=ProposalView)
def withdraw(
    request: Request,
    actor: Actor,
    proposal_id: UUID,
    body: WithdrawCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        guard_proposal(request, actor, session, proposal_id)

    def change(session):
        row = session.get(CompanyProposal, str(proposal_id))
        if row.status == "withdrawn" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        if row.revision_id:
            revision = session.scalar(
                select(ContentRevision)
                .where(ContentRevision.revision_id == row.revision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if revision.status == "published":
                revision.status, revision.version = "retired", revision.version + 1
                revision.retired_by, revision.retirement_reason, revision.retired_at = (
                    str(actor.subject),
                    body.reason,
                    datetime.now(UTC),
                )
                content_event(session, request, revision, "retired")
        row.status, row.version = "withdrawn", row.version + 1
        emit(session, request, row, actor)
        return {"proposal_id": row.proposal_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_proposal_withdraw:{proposal_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: proposal_view(
            session, session.get(CompanyProposal, str(proposal_id))
        ),
    )


def purge(session, subject):
    ids = list(
        session.scalars(
            select(CompanyProposal.proposal_id).where(
                (CompanyProposal.created_by == subject) | (CompanyProposal.reviewed_by == subject)
            )
        )
    )
    session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.operation.in_(
                [
                    f"company_proposal_{command}:{ref}"
                    for ref in ids
                    for command in ("update", "submit", "review", "withdraw")
                ]
            )
        )
    )
    revisions = list(
        session.scalars(
            select(CompanyProposal.revision_id).where(
                CompanyProposal.proposal_id.in_(ids), CompanyProposal.revision_id.is_not(None)
            )
        )
    )
    for ref in ids + revisions:
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.response.contains(ref)))
    session.execute(delete(Outbox).where(Outbox.envelope["aggregate_id"].as_string().in_(ids)))
    session.execute(delete(CompanyProposal).where(CompanyProposal.proposal_id.in_(ids)))


class ProposalSummary(Contract):
    proposal_id: UUID
    organization_id: UUID
    name: str
    status: Literal["draft", "submitted", "approved", "rejected", "withdrawn"]
    version: int
    digest: str


@router.get("", response_model=list[ProposalSummary])
def list_proposals(
    request: Request,
    actor: Actor,
    organization_id: UUID | None = None,
    status: Literal["draft", "submitted", "approved", "rejected", "withdrawn"] | None = None,
    after: UUID | None = None,
):
    reviewer = organization_id is None
    if reviewer:
        actor.require("content_admin", mfa=True)
    else:
        membership(request, actor, organization_id)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(CompanyProposal)
        if organization_id:
            query = query.where(CompanyProposal.organization_id == str(organization_id))
        if status or reviewer:
            query = query.where(CompanyProposal.status == (status or "submitted"))
        if after:
            query = query.where(CompanyProposal.proposal_id > str(after))
        rows = list(session.scalars(query.order_by(CompanyProposal.proposal_id).limit(50)))
        subjects = {str(actor.subject)} | {
            subject for row in rows for subject in related(session, row, actor)
        }
        for subject in sorted(subjects):
            subject_lock(session, subject, allow_blocked=True)
        subject_lock(session, actor.subject)
        result = []
        for row in rows:
            session.refresh(row)
            if (status or reviewer) and row.status != (status or "submitted"):
                continue
            if not related(session, row, actor).issubset(subjects):
                continue
            try:
                guarded = guard_proposal(
                    request, actor, session, row.proposal_id, reviewer=reviewer
                )
            except HTTPException as exc:
                if exc.status_code not in {403, 409}:
                    raise
                continue
            result.append(
                ProposalSummary(
                    proposal_id=guarded.proposal_id,
                    organization_id=guarded.organization_id,
                    name=guarded.name,
                    status=guarded.status,
                    version=guarded.version,
                    digest=guarded.digest,
                ).model_dump(mode="json")
            )
        return result
