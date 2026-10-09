from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import DateTime, String, UniqueConstraint, delete, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import IdempotencyRecord, consume_once, enqueue
from reverse_hr.events import EventEnvelope


class EmployerBase(DeclarativeBase):
    pass


class Organization(EmployerBase):
    __tablename__ = "organizations"
    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    verification_status: Mapped[str] = mapped_column(String(16))
    verification_reason: Mapped[str | None] = mapped_column(String(2000))
    verified_by: Mapped[str | None] = mapped_column(String(36))
    version: Mapped[int]
    trust_required: Mapped[bool] = mapped_column(default=False, server_default="0")


class Membership(EmployerBase):
    __tablename__ = "memberships"
    __table_args__ = (UniqueConstraint("organization_id", "subject"),)
    membership_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    subject: Mapped[str] = mapped_column(String(36), index=True)
    role: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(16), default="active")
    version: Mapped[int] = mapped_column(default=1)


class VerificationDecision(EmployerBase):
    __tablename__ = "verification_decisions"
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(2000))
    source: Mapped[str] = mapped_column(String(30))
    organization_version: Mapped[int]
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OwnershipRecovery(EmployerBase):
    __tablename__ = "ownership_recoveries"
    recovery_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    previous_membership_id: Mapped[str] = mapped_column(String(36))
    new_membership_id: Mapped[str] = mapped_column(String(36))
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(2000))
    organization_version: Mapped[int]
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class OwnershipRecoveryCommand(Contract):
    membership_id: UUID
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class OrganizationCommand(Contract):
    name: str = Field(min_length=1, max_length=200)


class OrganizationView(OrganizationCommand):
    organization_id: UUID
    verification_status: Literal["pending", "verified", "rejected"]
    verification_reason: str | None
    verified_by: UUID | None
    version: int


class MembershipCommand(Contract):
    subject: UUID
    role: Literal["recruiter", "technical_expert"]


class MembershipView(Contract):
    membership_id: UUID
    organization_id: UUID
    subject: UUID
    role: Literal["owner", "recruiter", "technical_expert"]
    status: Literal["active", "revoked"]
    version: int


class VerificationDecisionView(Contract):
    decision_id: UUID
    organization_id: UUID
    reviewer_id: UUID
    status: Literal["verified", "rejected"]
    reason: str
    source: Literal["manual_review"]
    organization_version: int
    decided_at: datetime


class VerificationCommand(Contract):
    status: Literal["verified", "rejected"]
    reason: str = Field(min_length=1, max_length=2000)


router = APIRouter(prefix="/v1/organizations", tags=["employer"])


def org_view(row, session, request):
    restricted = row.verified_by and not subject_visible(session, request, row.verified_by)
    return OrganizationView(
        organization_id=row.organization_id,
        name=row.name,
        verification_status=row.verification_status,
        verification_reason=None if restricted else row.verification_reason,
        verified_by=None if restricted else row.verified_by,
        version=row.version,
    ).model_dump(mode="json")


def membership_view(row):
    return MembershipView(
        membership_id=row.membership_id,
        organization_id=row.organization_id,
        subject=row.subject,
        role=row.role,
        status=row.status,
        version=row.version,
    ).model_dump(mode="json")


def require_member(session, organization_id, actor, owner=False):
    actor.require("employer")
    subject_lock(session, actor.subject)
    row = session.scalar(
        select(Membership).where(
            Membership.organization_id == str(organization_id),
            Membership.subject == str(actor.subject),
            Membership.status == "active",
        )
    )
    if row is None:
        raise HTTPException(404)
    if owner and row.role != "owner":
        raise HTTPException(403)
    return row


@router.post("", response_model=OrganizationView, status_code=201)
def create_organization(
    request: Request, actor: Actor, body: OrganizationCommand, idempotency: CommandKey
):
    actor.require("employer")

    def change(session):
        row = Organization(
            organization_id=str(uuid4()), name=body.name, verification_status="pending", version=1
        )
        session.add(row)
        session.add(
            Membership(
                membership_id=str(uuid4()),
                organization_id=row.organization_id,
                subject=str(actor.subject),
                role="owner",
            )
        )
        session.flush()
        enqueue(
            session,
            EventEnvelope(
                event_type="employer.organization_created.v1",
                producer="employer",
                correlation_id=request.state.trace_id,
                aggregate_id=UUID(row.organization_id),
                aggregate_version=1,
                payload={"organization_id": UUID(row.organization_id)},
            ),
        )
        return org_view(row, session, request)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_organization",
        idempotency,
        body.model_dump(),
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
        present=lambda session, result: visible_response(session, request, result),
    )


@router.get("", response_model=list[OrganizationView])
def list_organizations(request: Request, actor: Actor):
    actor.require("employer")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        rows = session.scalars(
            select(Organization)
            .join(
                Membership,
                Membership.organization_id == Organization.organization_id,
            )
            .where(Membership.subject == str(actor.subject), Membership.status == "active")
        )
        return [org_view(row, session, request) for row in rows]


@router.get("/{organization_id}", response_model=OrganizationView)
def get_organization(request: Request, actor: Actor, organization_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        require_member(session, organization_id, actor)
        return org_view(session.get(Organization, str(organization_id)), session, request)


@router.get("/{organization_id}/members", response_model=list[MembershipView])
def members(request: Request, actor: Actor, organization_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        require_member(session, organization_id, actor)
        return [
            membership_view(row)
            for row in session.scalars(
                select(Membership).where(
                    Membership.organization_id == str(organization_id),
                    ~Membership.subject.in_(
                        select(EmployerSubject.subject).where(EmployerSubject.blocked)
                    ),
                )
            )
            if subject_visible(session, request, row.subject)
        ]


@router.post("/{organization_id}/members", response_model=MembershipView, status_code=201)
def add_member(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    body: MembershipCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    # Recheck authorization even on an idempotent replay.
    with Session(request.app.state.engine) as session, session.begin():
        require_member(session, organization_id, actor, owner=True)
    version = int(if_match.strip('"'))

    def change(session):
        require_member(session, organization_id, actor, owner=True)
        result = session.execute(
            update(Organization)
            .where(
                Organization.organization_id == str(organization_id),
                Organization.version == version,
            )
            .values(version=version + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        row = Membership(
            membership_id=str(uuid4()),
            organization_id=str(organization_id),
            subject=str(body.subject),
            role=body.role,
        )
        session.add(row)
        session.flush()
        enqueue(
            session,
            EventEnvelope(
                event_type="employer.membership_created.v1",
                producer="employer",
                correlation_id=request.state.trace_id,
                aggregate_id=organization_id,
                aggregate_version=version + 1,
                payload={
                    "organization_id": organization_id,
                    "membership_id": UUID(row.membership_id),
                },
            ),
        )
        return membership_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"add_member:{organization_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": version},
        change,
        201,
        guard=lambda session: membership_guard(session, request, actor.subject, body.subject),
        present=lambda session, result: visible_response(session, request, result),
    )


@router.post("/{organization_id}/verification", response_model=OrganizationView)
def verify(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    body: VerificationCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("company_moderator", mfa=True)
    version = int(if_match.strip('"'))

    def change(session):
        row = session.get(Organization, str(organization_id))
        if row is None:
            raise HTTPException(404)
        result = session.execute(
            update(Organization)
            .where(
                Organization.organization_id == str(organization_id),
                Organization.version == version,
            )
            .values(
                verification_status=body.status,
                verification_reason=body.reason,
                verified_by=str(actor.subject),
                version=version + 1,
            )
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        session.add(
            VerificationDecision(
                decision_id=str(uuid4()),
                organization_id=str(organization_id),
                reviewer_id=str(actor.subject),
                status=body.status,
                reason=body.reason,
                source="manual_review",
                organization_version=row.version,
                decided_at=datetime.now(UTC),
            )
        )
        enqueue(
            session,
            EventEnvelope(
                event_type="employer.verification_changed.v1",
                producer="employer",
                correlation_id=request.state.trace_id,
                aggregate_id=organization_id,
                aggregate_version=row.version,
                payload={"organization_id": organization_id},
            ),
        )
        return org_view(row, session, request)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"verify:{organization_id}",
        idempotency,
        {"body": body.model_dump(), "version": version},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
        present=lambda session, result: visible_response(session, request, result),
    )


@router.get(
    "/{organization_id}/verification-history", response_model=list[VerificationDecisionView]
)
def verification_history(request: Request, actor: Actor, organization_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        if "company_moderator" in actor.roles:
            actor.require("company_moderator", mfa=True)
        else:
            require_member(session, organization_id, actor, owner=True)
        if session.get(Organization, str(organization_id)) is None:
            raise HTTPException(404)
        rows = session.scalars(
            select(VerificationDecision)
            .where(
                VerificationDecision.organization_id == str(organization_id),
                ~VerificationDecision.reviewer_id.in_(
                    select(EmployerSubject.subject).where(EmployerSubject.blocked)
                ),
            )
            .order_by(VerificationDecision.organization_version)
        )
        return [
            VerificationDecisionView(
                decision_id=row.decision_id,
                organization_id=row.organization_id,
                reviewer_id=row.reviewer_id,
                status=row.status,
                reason=row.reason,
                source=row.source,
                organization_version=row.organization_version,
                decided_at=row.decided_at,
            )
            for row in rows
            if subject_visible(session, request, row.reviewer_id)
        ]


@router.post("/{organization_id}/members/{membership_id}/revoke", response_model=MembershipView)
def revoke_member(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    membership_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    with Session(request.app.state.engine) as session, session.begin():
        require_member(session, organization_id, actor, owner=True)
    version = int(if_match.strip('"'))

    def change(session):
        require_member(session, organization_id, actor, owner=True)
        row = session.get(Membership, str(membership_id))
        if row is None or row.organization_id != str(organization_id):
            raise HTTPException(404)
        if row.role == "owner":
            raise HTTPException(409)
        result = session.execute(
            update(Membership)
            .where(
                Membership.membership_id == str(membership_id),
                Membership.version == version,
                Membership.status == "active",
            )
            .values(status="revoked", version=version + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        # Serialize organization commands and invalidate an already-read aggregate version.
        session.execute(
            update(Organization)
            .where(
                Organization.organization_id == str(organization_id),
            )
            .values(version=Organization.version + 1)
        )
        session.refresh(row)
        enqueue(
            session,
            EventEnvelope(
                event_type="employer.membership_revoked.v1",
                producer="employer",
                correlation_id=request.state.trace_id,
                aggregate_id=membership_id,
                aggregate_version=row.version,
                payload={"organization_id": organization_id, "membership_id": membership_id},
            ),
        )
        return membership_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"revoke_member:{membership_id}",
        idempotency,
        {"version": version, "organization_id": str(organization_id)},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
        present=lambda session, result: visible_response(session, request, result),
    )


class EmployerSubject(EmployerBase):
    __tablename__ = "employer_subjects"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    status: Mapped[str | None] = mapped_column(String(16))
    restricted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


@router.post("/{organization_id}/ownership-recovery", response_model=OrganizationView)
def recover_ownership(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    body: OwnershipRecoveryCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("company_moderator", mfa=True)
    version = int(if_match.strip('"'))

    def guard(session):
        # Resolve the immutable membership subject first, then lock actor/target in
        # the same order as membership creation and deletion consumers.
        target = session.get(Membership, str(body.membership_id))
        if target is None or target.organization_id != str(organization_id):
            raise HTTPException(404)
        previous_subjects = set(
            session.scalars(
                select(Membership.subject).where(
                    Membership.organization_id == str(organization_id),
                    Membership.role == "owner",
                )
            )
        )
        required = {str(actor.subject), target.subject}
        for subject in sorted(required | previous_subjects):
            subject_lock(session, subject, allow_blocked=subject not in required)
        if not subject_visible(session, request, target.subject):
            raise HTTPException(409)

    def change(session):
        org = session.scalar(
            select(Organization)
            .where(Organization.organization_id == str(organization_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if org is None:
            raise HTTPException(404)
        if org.version != version:
            raise HTTPException(409)
        members = list(
            session.scalars(
                select(Membership)
                .where(Membership.organization_id == str(organization_id))
                .execution_options(populate_existing=True)
            )
        )
        target = next(row for row in members if row.membership_id == str(body.membership_id))
        owners = [row for row in members if row.role == "owner"]
        if (
            target.status != "active"
            or target.role == "owner"
            or any(row.role == "owner" and row.status == "active" for row in members)
            or len(owners) != 1
        ):
            raise HTTPException(409)
        previous = owners[0]
        restriction = session.get(EmployerSubject, previous.subject)
        if restriction is None or not restriction.blocked or not restriction.request_id:
            raise HTTPException(409)
        # Keep the previous revoked membership for the separate retention process.
        previous.role = "recruiter"
        previous.version += 1
        target.role = "owner"
        target.version += 1
        org.version += 1
        recovery_id = uuid4()
        session.add(
            OwnershipRecovery(
                recovery_id=str(recovery_id),
                organization_id=str(organization_id),
                previous_membership_id=previous.membership_id,
                new_membership_id=target.membership_id,
                reviewer_id=str(actor.subject),
                reason=body.reason,
                organization_version=org.version,
                decided_at=datetime.now(UTC),
            )
        )
        enqueue(
            session,
            EventEnvelope(
                event_type="employer.ownership_recovered.v1",
                producer="employer",
                correlation_id=request.state.trace_id,
                aggregate_id=organization_id,
                aggregate_version=org.version,
                payload={"organization_id": organization_id, "recovery_id": recovery_id},
            ),
        )
        return org_view(org, session, request)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"recover_ownership:{organization_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": version},
        change,
        guard=guard,
        present=lambda session, result: visible_response(session, request, result),
    )


def subject_lock(session, subject, *, allow_blocked=False):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(EmployerSubject)
        .values(subject=str(subject), blocked=False)
        .on_conflict_do_nothing(index_elements=["subject"])
    )
    row = session.scalar(
        select(EmployerSubject)
        .where(EmployerSubject.subject == str(subject))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.blocked and not allow_blocked:
        raise HTTPException(409)
    return row


def lock_subjects(session, *subjects):
    # Membership creation must not lock actor/target in opposite orders.
    for subject in sorted(set(map(str, subjects))):
        subject_lock(session, subject)


def process_deletion_request(session, event):
    """Restrict records awaiting ownership/retention resolution; never fabricate deletion."""
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = str(event.payload["candidate_id"])
        row = subject_lock(session, subject, allow_blocked=True)
        request_id = str(event.aggregate_id)
        if row.request_id is not None and row.request_id != request_id:
            raise HTTPException(409)
        memberships = list(
            session.scalars(
                select(Membership)
                .where(Membership.subject == subject)
                .order_by(Membership.organization_id)
                .with_for_update()
            )
        )
        retained = (
            bool(memberships)
            or session.scalar(
                select(Organization.organization_id)
                .where(Organization.verified_by == subject)
                .limit(1)
            )
            is not None
            or session.scalar(
                select(VerificationDecision.decision_id)
                .where(VerificationDecision.reviewer_id == subject)
                .limit(1)
            )
            is not None
            or session.scalar(
                select(OwnershipRecovery.recovery_id)
                .where(OwnershipRecovery.reviewer_id == subject)
                .limit(1)
            )
            is not None
        )
        for member in memberships:
            if member.status == "active":
                member.status = "revoked"
                member.version += 1
                session.execute(
                    update(Organization)
                    .where(Organization.organization_id == member.organization_id)
                    .values(version=Organization.version + 1)
                )
                enqueue(
                    session,
                    EventEnvelope(
                        event_type="employer.membership_revoked.v1",
                        producer="employer",
                        correlation_id=event.correlation_id,
                        aggregate_id=UUID(member.membership_id),
                        aggregate_version=member.version,
                        payload={
                            "organization_id": UUID(member.organization_id),
                            "membership_id": UUID(member.membership_id),
                        },
                    ),
                )
        from reverse_hr.domains.employer_trust import scrub

        scrub(session, subject)
        # Other actors' cached add_member responses also contain this subject's UUID.
        session.execute(
            delete(IdempotencyRecord).where(
                (IdempotencyRecord.actor_id == subject)
                | IdempotencyRecord.response.contains(subject)
            )
        )
        first = row.request_id is None
        row.blocked, row.request_id = True, request_id
        row.status = "restricted" if retained else "deleted"
        row.restricted_at = datetime.now(UTC)
        if first:
            enqueue(
                session,
                EventEnvelope(
                    event_type=f"employer.data_{row.status}.v1",
                    producer="employer",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    aggregate_version=1,
                    payload=event.payload,
                ),
            )

    return consume_once(session, "employer.deletion_request", event, apply)


def membership_guard(session, request, actor, target):
    lock_subjects(session, actor, target)
    if not subject_visible(session, request, target):
        raise HTTPException(409)


def subject_visible(session, request, subject):
    state = session.get(EmployerSubject, str(subject))
    if state is not None and state.blocked:
        return False
    # A response may contain the same reviewer many times. Deduplicate checks only
    # within this HTTP request, never across requests or in a shared positive cache.
    checks = getattr(request.state, "visibility_checks", None)
    if checks is None:
        checks = request.state.visibility_checks = {}
    key = str(subject)
    if key not in checks:
        try:
            request.app.state.processing_access.check(UUID(key))
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            checks[key] = False
        else:
            checks[key] = True
    return checks[key]


def visible_response(session, request, result):
    """Apply current disclosure rules to fresh AND saved command responses."""
    if "subject" in result and not subject_visible(session, request, result["subject"]):
        raise HTTPException(409)
    reviewer = result.get("verified_by")
    if reviewer and not subject_visible(session, request, reviewer):
        return result | {"verified_by": None, "verification_reason": None}
    return result
