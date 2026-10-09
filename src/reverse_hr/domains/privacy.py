from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import Response
from sqlalchemy import DateTime, String, delete, select, update
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Consent, ConsentCommand, Contract
from reverse_hr.db import IdempotencyRecord, Outbox, consume_once, enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import (
    ASSESSMENT_REQUEST_CONTEXT,
    ASSESSMENT_RESPONSE_CONTEXT,
    REQUEST_CONTEXT,
    RESPONSE_CONTEXT,
    AssessmentPermissionRequest,
    AssessmentPermissionStatus,
    ProcessingRequest,
    ProcessingStatus,
    canonical,
    fresh,
    sign,
    verify,
)
from reverse_hr.recording_access import REQUEST as RECORDING_REQUEST
from reverse_hr.recording_access import RESPONSE as RECORDING_RESPONSE
from reverse_hr.recording_access import RecordingRequest, RecordingStatus
from reverse_hr.settings import SERVICES


class PrivacyBase(DeclarativeBase):
    pass


class ConsentRecord(PrivacyBase):
    __tablename__ = "consents"
    consent_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    purpose: Mapped[str] = mapped_column(String(50))
    document_version: Mapped[str] = mapped_column(String(100))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContactGrant(PrivacyBase):
    __tablename__ = "contact_grants"
    grant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invitation_id: Mapped[str] = mapped_column(String(36), unique=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36))
    consent_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ContactGrantView(Contract):
    grant_id: UUID
    invitation_id: UUID
    candidate_id: UUID
    organization_id: UUID
    consent_id: UUID
    status: Literal["active", "revoked", "expired"]
    version: int
    expires_at: datetime


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def grant_view(row):
    return ContactGrantView(
        grant_id=row.grant_id,
        invitation_id=row.invitation_id,
        candidate_id=row.candidate_id,
        organization_id=row.organization_id,
        consent_id=row.consent_id,
        status="expired"
        if row.status == "active" and utc(row.expires_at) <= datetime.now(UTC)
        else row.status,
        version=row.version,
        expires_at=utc(row.expires_at),
    ).model_dump(mode="json")


def grant_event(session, row, correlation_id, event_type):
    enqueue(
        session,
        EventEnvelope(
            event_type=event_type,
            producer="privacy",
            correlation_id=correlation_id,
            aggregate_id=UUID(row.grant_id),
            aggregate_version=row.version,
            payload={
                "grant_id": UUID(row.grant_id),
                "candidate_id": UUID(row.candidate_id),
                "organization_id": UUID(row.organization_id),
            },
        ),
    )


def process_accepted_invitation(session, event: EventEnvelope, *, ttl_days=30):
    """Internal consumer only; transport MUST authenticate Hiring before calling.

    There is deliberately no public route for creating grants from client-supplied events.
    Inbox, consent lock, grant and outbox are part of the caller's transaction.
    """
    required = {"candidate_id", "organization_id", "invitation_id", "consent_id"}
    if (
        event.producer != "hiring"
        or event.event_type != "hiring.invitation_accepted.v1"
        or set(event.payload) != required
        or not 1 <= ttl_days <= 365
        or event.aggregate_id != event.payload["invitation_id"]
    ):
        raise HTTPException(409)

    def apply(session, event):
        payload = event.payload
        subject_lock(session, payload["candidate_id"])
        existing = session.scalar(
            select(ContactGrant).where(ContactGrant.invitation_id == str(payload["invitation_id"]))
        )
        if existing:
            if (
                existing.candidate_id != str(payload["candidate_id"])
                or existing.organization_id != str(payload["organization_id"])
                or existing.consent_id != str(payload["consent_id"])
            ):
                raise HTTPException(409)
            return  # A late event can never replace the revocation tombstone.
        consent = session.scalar(
            select(ConsentRecord)
            .where(ConsentRecord.consent_id == str(payload["consent_id"]))
            .with_for_update()
        )
        if (
            consent is None
            or consent.candidate_id != str(payload["candidate_id"])
            or consent.purpose != "contact_disclosure"
            or consent.status != "active"
            or consent.document_version != POLICIES["contact_disclosure"]
        ):
            raise HTTPException(409)
        expires_at = utc(event.occurred_at) + timedelta(days=ttl_days)
        if expires_at <= datetime.now(UTC) or utc(event.occurred_at) > datetime.now(
            UTC
        ) + timedelta(minutes=2):
            raise HTTPException(409)
        row = ContactGrant(
            grant_id=str(uuid4()),
            invitation_id=str(payload["invitation_id"]),
            candidate_id=str(payload["candidate_id"]),
            organization_id=str(payload["organization_id"]),
            consent_id=consent.consent_id,
            status="active",
            version=1,
            expires_at=expires_at,
        )
        session.add(row)
        session.flush()
        grant_event(session, row, event.correlation_id, "privacy.contact_grant_created.v1")

    return consume_once(session, "privacy.accepted_invitation", event, apply)


def permitted_contact_grant(session, candidate_id, organization_id, *, now=None):
    """Privacy-owned current lookup; no sensitive data or remote authorization bypass."""
    state = session.get(PrivacySubject, str(candidate_id))
    if state is not None and state.blocked:
        return None
    return session.scalar(
        select(ContactGrant)
        .join(
            ConsentRecord,
            ConsentRecord.consent_id == ContactGrant.consent_id,
        )
        .where(
            ContactGrant.candidate_id == str(candidate_id),
            ContactGrant.organization_id == str(organization_id),
            ContactGrant.status == "active",
            ContactGrant.expires_at > (now or datetime.now(UTC)),
            ConsentRecord.status == "active",
            ConsentRecord.purpose == "contact_disclosure",
            ConsentRecord.document_version == POLICIES["contact_disclosure"],
        )
    )


router = APIRouter(prefix="/v1/consents", tags=["privacy"])
# Technical demo policy. Not legally reviewed consent wording.
EXTERNAL_NOTIFICATION_PURPOSES = {
    "external_service_notifications",
    "external_marketing_notifications",
}

POLICIES = {
    purpose: "demo-v1"
    for purpose in (
        "assessment",
        "recording",
        "profile_publication",
        "ats_export",
        "achievement_import",
        "achievement_publication",
        "contact_disclosure",
        "company_result_disclosure",
        "company_task_subscription",
        "resume_publication",
        "external_service_notifications",
        "external_marketing_notifications",
    )
}


def view(row):
    return Consent(
        consent_id=row.consent_id,
        purpose=row.purpose,
        document_version=row.document_version,
        status=row.status,
        version=row.version,
    ).model_dump(mode="json")


@router.get("/policies")
def policies(actor: Actor) -> dict[str, str]:
    return (
        POLICIES
        if "candidate" in actor.roles
        else {purpose: POLICIES[purpose] for purpose in EXTERNAL_NOTIFICATION_PURPOSES}
    )


@router.get("", response_model=list[Consent])
def list_consents(request: Request, actor: Actor):
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        return [
            view(row)
            for row in session.scalars(
                select(ConsentRecord)
                .where(ConsentRecord.candidate_id == str(actor.subject))
                .where(
                    ConsentRecord.purpose.in_(EXTERNAL_NOTIFICATION_PURPOSES)
                    if "candidate" not in actor.roles
                    else True
                )
                .order_by(ConsentRecord.granted_at)
            )
        ]


@router.post("", response_model=Consent, status_code=201)
def grant_consent(request: Request, actor: Actor, body: ConsentCommand, idempotency: CommandKey):
    if body.purpose not in EXTERNAL_NOTIFICATION_PURPOSES:
        actor.require("candidate")
    if POLICIES[body.purpose] != body.document_version:
        raise HTTPException(409)

    def change(session):
        row = ConsentRecord(
            consent_id=str(uuid4()),
            candidate_id=str(actor.subject),
            **body.model_dump(),
            status="active",
            version=1,
            granted_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        enqueue(
            session,
            EventEnvelope(
                event_type="privacy.consent_granted.v1",
                producer="privacy",
                correlation_id=request.state.trace_id,
                aggregate_id=UUID(row.consent_id),
                aggregate_version=1,
                payload={"candidate_id": actor.subject, "consent_id": UUID(row.consent_id)},
            ),
        )
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "grant_consent",
        idempotency,
        body.model_dump(),
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@router.post("/{consent_id}/revoke", response_model=Consent)
def revoke_consent(
    request: Request,
    actor: Actor,
    consent_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    version = int(if_match.strip('"'))

    def guard(session):
        subject_lock(session, actor.subject)
        row = session.get(ConsentRecord, str(consent_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        if row.purpose not in EXTERNAL_NOTIFICATION_PURPOSES:
            actor.require("candidate")

    def change(session):
        row = session.get(ConsentRecord, str(consent_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        result = session.execute(
            update(ConsentRecord)
            .where(
                ConsentRecord.consent_id == str(consent_id),
                ConsentRecord.version == version,
                ConsentRecord.status == "active",
            )
            .values(status="revoked", version=version + 1, revoked_at=datetime.now(UTC))
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        grants = list(
            session.scalars(
                select(ContactGrant)
                .where(
                    ContactGrant.consent_id == str(consent_id),
                    ContactGrant.status == "active",
                )
                .with_for_update()
            )
        )
        for grant in grants:
            grant.status = "revoked"
            grant.version += 1
            grant.revoked_at = datetime.now(UTC)
            grant_event(session, grant, request.state.trace_id, "privacy.contact_grant_revoked.v1")
        enqueue(
            session,
            EventEnvelope(
                event_type="privacy.consent_revoked.v1",
                producer="privacy",
                correlation_id=request.state.trace_id,
                aggregate_id=consent_id,
                aggregate_version=row.version,
                payload={"candidate_id": actor.subject, "consent_id": consent_id},
            ),
        )
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"revoke_consent:{consent_id}",
        idempotency,
        {"version": version},
        change,
        guard=guard,
    )


grants_router = APIRouter(prefix="/v1/contact-grants", tags=["privacy"])


@grants_router.get("", response_model=list[ContactGrantView])
def list_grants(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        return [
            grant_view(row)
            for row in session.scalars(
                select(ContactGrant).where(ContactGrant.candidate_id == str(actor.subject))
            )
        ]


@grants_router.post("/{grant_id}/revoke", response_model=ContactGrantView)
def revoke_grant(
    request: Request,
    actor: Actor,
    grant_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    version = int(if_match.strip('"'))

    def change(session):
        row = session.get(ContactGrant, str(grant_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        result = session.execute(
            update(ContactGrant)
            .where(
                ContactGrant.grant_id == str(grant_id),
                ContactGrant.version == version,
                ContactGrant.status == "active",
            )
            .values(status="revoked", version=version + 1, revoked_at=datetime.now(UTC))
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        grant_event(session, row, request.state.trace_id, "privacy.contact_grant_revoked.v1")
        return grant_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"revoke_grant:{grant_id}",
        idempotency,
        {"version": version},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
    )


consents_router = router
router = APIRouter()
router.include_router(consents_router)
router.include_router(grants_router)


class BackupStoreIdentity(PrivacyBase):
    __tablename__ = "backup_store_identity"
    name: Mapped[str] = mapped_column(String(16), primary_key=True)
    fingerprint: Mapped[str] = mapped_column(String(64))


class PrivacySubject(PrivacyBase):
    """Durable restriction tombstone; retained for reapplying deletion after restore."""

    __tablename__ = "privacy_subjects"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]


class DeletionRequest(PrivacyBase):
    __tablename__ = "deletion_requests"
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), unique=True)
    requested_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_attempts: Mapped[int] = mapped_column(default=0)
    backup_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    backup_error: Mapped[str | None] = mapped_column(String(32))


class DeletionTarget(PrivacyBase):
    __tablename__ = "deletion_targets"
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    service: Mapped[str] = mapped_column(String(50), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DeletionView(Contract):
    request_id: UUID
    candidate_id: UUID
    status: Literal["in_progress", "completed"]
    requested_at: datetime
    completed_at: datetime | None = None
    services: dict[str, Literal["pending", "restricted", "deleted"]]
    backup_attempts: int = 0
    backup_error: Literal["archive_unavailable"] | None = None
    backup_retry_at: datetime | None = None


def subject_lock(session, candidate_id, *, allow_blocked=False):
    """Serialize all Privacy operations with deletion, even for a new subject.

    Both supported dialects implement atomic insert-if-absent. PostgreSQL locks
    the resulting row until the enclosing transaction commits.
    """
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(PrivacySubject)
        .values(candidate_id=str(candidate_id), blocked=False)
        .on_conflict_do_nothing(index_elements=["candidate_id"])
    )
    state = session.scalar(
        select(PrivacySubject)
        .where(PrivacySubject.candidate_id == str(candidate_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if state.blocked and not allow_blocked:
        raise HTTPException(409)
    return state


def deletion_view(session, row):
    targets = {
        target.service: target.status
        for target in session.scalars(
            select(DeletionTarget).where(DeletionTarget.request_id == row.request_id)
        )
    }
    return DeletionView(
        request_id=row.request_id,
        candidate_id=row.candidate_id,
        status="completed"
        if row.completed_at is not None
        and set(targets) == set(SERVICES)
        and all(value == "deleted" for value in targets.values())
        else "in_progress",
        requested_at=utc(row.requested_at),
        completed_at=utc(row.completed_at) if row.completed_at else None,
        backup_attempts=row.backup_attempts,
        backup_error=row.backup_error,
        backup_retry_at=utc(row.backup_retry_at) if row.backup_retry_at else None,
        services=targets,
    ).model_dump(mode="json")


def process_deletion_ack(session, event):
    """Called only after the signed transport authenticates the producing service."""
    if (
        event.producer not in SERVICES
        or event.producer == "privacy"
        or event.event_type
        not in {f"{event.producer}.data_deleted.v1", f"{event.producer}.data_restricted.v1"}
        or set(event.payload) != {"request_id", "candidate_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
    ):
        raise HTTPException(409)

    def apply(session, event):
        row = session.get(DeletionRequest, str(event.payload["request_id"]))
        if row is None or row.candidate_id != str(event.payload["candidate_id"]):
            raise HTTPException(409)
        subject_lock(session, row.candidate_id, allow_blocked=True)
        session.refresh(row)  # Another ACK may have completed while this transaction waited.
        target = session.get(DeletionTarget, (row.request_id, event.producer))
        if target is None or utc(event.occurred_at) < utc(row.requested_at):
            raise HTTPException(409)
        if utc(event.occurred_at) > datetime.now(UTC) + timedelta(minutes=2):
            raise HTTPException(409)
        if target.status != "deleted":
            target.status = (
                "restricted" if event.event_type.endswith(".data_restricted.v1") else "deleted"
            )
            target.acknowledged_at = datetime.now(UTC)
        finalize_deletion(session, row, event.correlation_id)

    return consume_once(session, "privacy.deletion_ack", event, apply)


deletions_router = APIRouter(prefix="/v1/deletion-requests", tags=["privacy"])


@deletions_router.post("", response_model=DeletionView, status_code=202)
def request_deletion(request: Request, actor: Actor, idempotency: CommandKey):

    def change(session):
        state = subject_lock(session, actor.subject, allow_blocked=True)
        existing = session.scalar(
            select(DeletionRequest).where(DeletionRequest.candidate_id == str(actor.subject))
        )
        if existing:
            return deletion_view(session, existing)
        state.blocked = True
        now = datetime.now(UTC)
        row = DeletionRequest(
            request_id=str(uuid4()), candidate_id=str(actor.subject), requested_at=now
        )
        session.add(row)
        for consent in session.scalars(
            select(ConsentRecord)
            .where(
                ConsentRecord.candidate_id == str(actor.subject), ConsentRecord.status == "active"
            )
            .with_for_update()
        ):
            consent.status, consent.revoked_at = "revoked", now
            consent.version += 1
            enqueue(
                session,
                EventEnvelope(
                    event_type="privacy.consent_revoked.v1",
                    producer="privacy",
                    correlation_id=request.state.trace_id,
                    aggregate_id=UUID(consent.consent_id),
                    aggregate_version=consent.version,
                    payload={"candidate_id": actor.subject, "consent_id": UUID(consent.consent_id)},
                ),
            )
        for grant in session.scalars(
            select(ContactGrant)
            .where(ContactGrant.candidate_id == str(actor.subject), ContactGrant.status == "active")
            .with_for_update()
        ):
            grant.status, grant.revoked_at = "revoked", now
            grant.version += 1
            grant_event(session, grant, request.state.trace_id, "privacy.contact_grant_revoked.v1")
        for service in SERVICES:
            session.add(
                DeletionTarget(
                    request_id=row.request_id,
                    service=service,
                    status="restricted" if service == "privacy" else "pending",
                )
            )
        enqueue(
            session,
            EventEnvelope(
                event_type="privacy.deletion_requested.v1",
                producer="privacy",
                correlation_id=request.state.trace_id,
                aggregate_id=UUID(row.request_id),
                aggregate_version=1,
                payload={"candidate_id": actor.subject, "request_id": UUID(row.request_id)},
            ),
        )
        session.flush()
        return deletion_view(session, row)

    return execute(
        request.app.state.engine, actor.subject, "request_deletion", idempotency, {}, change, 202
    )


@deletions_router.get("/me", response_model=DeletionView)
def get_deletion(request: Request, actor: Actor):
    with Session(request.app.state.engine) as session:
        row = session.scalar(
            select(DeletionRequest).where(DeletionRequest.candidate_id == str(actor.subject))
        )
        if row is None:
            raise HTTPException(404)
        return deletion_view(session, row)


router.include_router(deletions_router)


class ProcessingNonce(PrivacyBase):
    __tablename__ = "processing_nonces"
    requester: Mapped[str] = mapped_column(String(50), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)


@router.post("/internal/v1/processing-status", response_model=ProcessingStatus, tags=["internal"])
def processing_status(
    request: Request,
    body: ProcessingRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    return signed_status(
        request,
        body,
        signature,
        REQUEST_CONTEXT,
        RESPONSE_CONTEXT,
        ProcessingStatus,
        lambda session, body, subject: (
            (subject is None or not subject.blocked)
            and not processing_restricted(session, body.candidate_id, domain=body.requester)
        ),
    )


@router.post(
    "/internal/v1/assessment-permission",
    response_model=AssessmentPermissionStatus,
    tags=["internal"],
)
def assessment_permission(
    request: Request,
    body: AssessmentPermissionRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    def allowed(session, body, subject):
        consent = session.get(ConsentRecord, str(body.consent_id))
        return bool(
            (subject is None or not subject.blocked)
            and consent is not None
            and consent.candidate_id == str(body.candidate_id)
            and not processing_restricted(
                session, body.candidate_id, domain=body.requester, purpose="assessment"
            )
            and consent.purpose == "assessment"
            and consent.status == "active"
            and consent.document_version == "demo-v1"
        )

    return signed_status(
        request,
        body,
        signature,
        ASSESSMENT_REQUEST_CONTEXT,
        ASSESSMENT_RESPONSE_CONTEXT,
        AssessmentPermissionStatus,
        allowed,
    )


def signed_status(
    request, body, signature, request_context, response_context, response_model, allowed
):
    from reverse_hr.event_transport import Signatures

    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(request.app.state, "privacy_signatures", None)
        if signatures is None:
            signatures = Signatures.from_settings(request.app.state.settings)
            request.app.state.privacy_signatures = signatures
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, body.requester, signature, request_context, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(ProcessingNonce).where(ProcessingNonce.expires_at < now))
            session.add(
                ProcessingNonce(
                    requester=body.requester,
                    nonce=str(body.nonce),
                    expires_at=now + timedelta(seconds=60),
                )
            )
            session.flush()
            subject = session.get(PrivacySubject, str(body.candidate_id))
            status = response_model(
                **(body.model_dump() | {"issued_at": now}),
                allowed=allowed(session, body, subject),
            )
            response_signature = sign(signatures, response_context, status)
        return Response(
            content=canonical(status),
            media_type="application/json",
            headers={"X-HR-Signature": response_signature, "Cache-Control": "no-store"},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc


def finalize_deletion(session, row, correlation_id, *, purge_backups=False):
    """Caller holds the subject lock; external owners must all confirm deletion.

    Keep the restriction/job ledger and deletion protocol outbox. Purge only
    this subject's business rows, responses and obsolete consent/grant events.
    """
    if row.completed_at is not None:
        return False
    targets = {
        target.service: target
        for target in session.scalars(
            select(DeletionTarget).where(DeletionTarget.request_id == row.request_id)
        )
    }
    external = set(SERVICES) - {"privacy"}
    if set(targets) != set(SERVICES) or any(targets[name].status != "deleted" for name in external):
        return False
    from reverse_hr.backup_archive import bind

    archive = bind(session)
    if archive is not None:
        # The signed ACK commits promptly. DeletionRequest is the durable cleanup job;
        # the dedicated worker retries storage failures without losing that ACK.
        if not purge_backups:
            return False
        archive.purge_subject(row.candidate_id)
    from reverse_hr.domains.privacy_company_results import CompanyResultGrant

    session.execute(
        delete(CompanyResultGrant).where(CompanyResultGrant.candidate_id == row.candidate_id)
    )
    from reverse_hr.domains.privacy_requests import scrub as scrub_requests

    scrub_requests(session, row.candidate_id)
    session.execute(delete(ContactGrant).where(ContactGrant.candidate_id == row.candidate_id))
    session.execute(delete(ConsentRecord).where(ConsentRecord.candidate_id == row.candidate_id))
    session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == row.candidate_id,
            IdempotencyRecord.operation != "request_deletion",
        )
    )
    session.execute(
        delete(Outbox).where(
            Outbox.envelope["payload"]["candidate_id"].as_string() == row.candidate_id,
            Outbox.envelope["event_type"]
            .as_string()
            .in_(
                [
                    "privacy.consent_granted.v1",
                    "privacy.consent_revoked.v1",
                    "privacy.contact_grant_created.v1",
                    "privacy.contact_grant_revoked.v1",
                ]
            ),
        )
    )
    now = datetime.now(UTC)
    own = targets["privacy"]
    own.status, own.acknowledged_at = "deleted", now
    row.completed_at = now
    for event_type, version in (
        ("privacy.data_deleted.v1", 1),
        ("privacy.deletion_completed.v1", 2),
    ):
        enqueue(
            session,
            EventEnvelope(
                event_type=event_type,
                producer="privacy",
                correlation_id=correlation_id,
                aggregate_id=UUID(row.request_id),
                aggregate_version=version,
                payload={
                    "request_id": UUID(row.request_id),
                    "candidate_id": UUID(row.candidate_id),
                },
            ),
        )
    return True


@router.post("/internal/v1/recording-permission", response_model=RecordingStatus, tags=["internal"])
def recording_permission(
    request: Request,
    body: RecordingRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    def allowed(session, body, subject):
        consent = session.get(ConsentRecord, str(body.consent_id))
        return bool(
            (subject is None or not subject.blocked)
            and consent is not None
            and consent.candidate_id == str(body.candidate_id)
            and not processing_restricted(
                session, body.candidate_id, domain=body.requester, purpose="recording"
            )
            and consent.purpose == "recording"
            and consent.status == "active"
            and consent.document_version == "demo-v1"
        )

    return signed_status(
        request, body, signature, RECORDING_REQUEST, RECORDING_RESPONSE, RecordingStatus, allowed
    )


def processing_restricted(session, candidate, *, domain=None, purpose=None):
    from reverse_hr.domains.privacy_requests import restriction

    return restriction(session, candidate, domain=domain, purpose=purpose)
