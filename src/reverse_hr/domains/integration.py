"""Durable fixed-adapter sync and ATS export jobs; sensitive payloads are fetched fresh."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, execute
from reverse_hr.contracts import ContactView, Contract
from reverse_hr.db import IdempotencyRecord, Outbox, consume_once, enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.exchange import ExchangeReceipt, ExchangeRequest, payload_digest, respond
from reverse_hr.market_access import Signature
from reverse_hr.market_contracts import CandidateCard
from reverse_hr.market_state import NonceColumns, SubjectColumns, lock


class IntegrationBase(DeclarativeBase):
    pass


class IntegrationSubject(SubjectColumns, IntegrationBase):
    __tablename__ = "integration_subjects"


class IntegrationNonce(NonceColumns, IntegrationBase):
    __tablename__ = "integration_nonces"


class DeliveryCounter(IntegrationBase):
    __tablename__ = "ats_delivery_counters"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    sequence: Mapped[int]


class Job(IntegrationBase):
    __tablename__ = "integration_jobs"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    connection_id: Mapped[str | None] = mapped_column(String(36), index=True)
    organization_id: Mapped[str | None] = mapped_column(String(36), index=True)
    invitation_id: Mapped[str | None] = mapped_column(String(36))
    consent_id: Mapped[str | None] = mapped_column(String(36))
    sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))
    version: Mapped[int]
    attempts: Mapped[int]
    lease_id: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(32))
    external_id: Mapped[str | None] = mapped_column(String(36))
    external_status: Mapped[str | None] = mapped_column(String(24))
    status_sequence: Mapped[int]
    payload_digest: Mapped[str | None] = mapped_column(String(64))


class ATSStatusReceipt(IntegrationBase):
    __tablename__ = "ats_status_receipts"
    receipt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    __table_args__ = (UniqueConstraint("job_id", "sequence"),)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))


class SyncCommand(Contract):
    connection_id: UUID


class ExportCommand(Contract):
    candidate_id: UUID
    organization_id: UUID
    invitation_id: UUID
    consent_id: UUID


class JobView(Contract):
    job_id: UUID
    kind: Literal["sync", "ats"]
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    version: int
    attempts: int
    candidate_id: UUID
    connection_id: UUID | None
    organization_id: UUID | None
    external_id: UUID | None
    external_status: Literal["received", "interview", "offer", "hired", "rejected"] | None
    status_sequence: int
    error_code: str | None


router = APIRouter(prefix="/v1/integrations", tags=["integration"])
internal_router = APIRouter(prefix="/internal/v1/exchange", tags=["internal-integration"])


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def fence(request, session, candidate, actor=None):
    for subject in sorted({str(candidate)} | ({str(actor)} if actor else set())):
        lock(session, IntegrationSubject, subject)
        request.app.state.processing_access.check(UUID(subject))


def demo(request):
    if request.app.state.settings.deployment_mode != "demo":
        raise HTTPException(409, "Demo integrations disabled in production")


def view(row):
    return JobView(**{key: getattr(row, key) for key in JobView.model_fields}).model_dump(
        mode="json"
    )


def new_job(actor, candidate, kind, **values):
    return Job(
        job_id=str(uuid4()),
        candidate_id=str(candidate),
        actor_id=str(actor),
        kind=kind,
        sequence=0,
        status="pending",
        version=1,
        attempts=0,
        available_at=datetime.now(UTC),
        created_at=datetime.now(UTC),
        status_sequence=0,
        **values,
    )


def membership(request, actor, organization):
    request.app.state.market_access.require(
        "employer",
        "membership",
        candidate_id=UUID(str(actor)),
        actor_id=UUID(str(actor)),
        organization_id=UUID(str(organization)),
    )


def export_payload(request, row):
    demo(request)
    access = request.app.state.market_access
    candidate, organization, invitation, actor = (
        UUID(row.candidate_id),
        UUID(row.organization_id),
        UUID(row.invitation_id),
        UUID(row.actor_id),
    )
    request.app.state.processing_access.check(candidate)
    request.app.state.processing_access.check(actor)
    membership(request, actor, organization)
    access.require(
        "privacy",
        "purpose-permission",
        candidate_id=candidate,
        consent_id=UUID(row.consent_id),
        consent_purpose="ats_export",
    )
    access.require(
        "hiring",
        "resume-permission",
        candidate_id=candidate,
        actor_id=actor,
        organization_id=organization,
        invitation_id=invitation,
    )
    profile = CandidateCard.model_validate(
        access.require("candidate", "profile", candidate_id=candidate).data
    )
    contacts = ContactView.model_validate(
        access.require(
            "candidate",
            "contacts",
            candidate_id=candidate,
            actor_id=actor,
            organization_id=organization,
            invitation_id=invitation,
        ).data
    )
    if (
        profile.candidate_id != candidate
        or contacts.candidate_id != candidate
        or contacts.organization_id != organization
    ):
        raise HTTPException(503)
    return dict(
        job_id=row.job_id,
        candidate_id=row.candidate_id,
        organization_id=row.organization_id,
        sequence=row.sequence,
        demo=True,
        actor_id=row.actor_id,
        profile=profile.model_dump(mode="json"),
        contacts=contacts.model_dump(mode="json"),
    )


@router.post("/syncs", response_model=JobView, status_code=202)
def sync(request: Request, actor: Actor, body: SyncCommand, idempotency: CommandKey):
    actor.require("candidate")
    demo(request)
    request.app.state.exchange_access.call(
        "achievements",
        "connection",
        actor.subject,
        body.connection_id,
        connection_id=str(body.connection_id),
    )

    def guard(session):
        fence(request, session, actor.subject)
        request.app.state.exchange_access.call(
            "achievements",
            "connection",
            actor.subject,
            body.connection_id,
            connection_id=str(body.connection_id),
        )

    def change(session):
        if session.scalar(
            select(Job).where(
                Job.connection_id == str(body.connection_id), Job.status.in_(["pending", "running"])
            )
        ):
            raise HTTPException(409, "Synchronization already queued")
        recent = session.scalar(
            select(Job).where(
                Job.connection_id == str(body.connection_id),
                Job.created_at > datetime.now(UTC) - timedelta(seconds=30),
            )
        )
        if recent:
            raise HTTPException(409, "Synchronization frequency limited")
        row = new_job(actor.subject, actor.subject, "sync", connection_id=str(body.connection_id))
        session.add(row)
        return {"job_id": row.job_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "integration_sync",
        idempotency,
        body.model_dump(mode="json"),
        change,
        202,
        guard=guard,
        present=lambda session, result: view(session.get(Job, result["job_id"])),
    )


@router.post("/ats-exports", response_model=JobView, status_code=202)
def export(request: Request, actor: Actor, body: ExportCommand, idempotency: CommandKey):
    actor.require("employer")
    provisional = new_job(
        actor.subject,
        body.candidate_id,
        "ats",
        organization_id=str(body.organization_id),
        invitation_id=str(body.invitation_id),
        consent_id=str(body.consent_id),
    )
    export_payload(request, provisional)

    def guard(session):
        fence(request, session, body.candidate_id, actor.subject)
        export_payload(request, provisional)

    def change(session):
        counter = session.get(DeliveryCounter, (str(body.candidate_id), str(body.organization_id)))
        if counter is None:
            counter = DeliveryCounter(
                candidate_id=str(body.candidate_id),
                organization_id=str(body.organization_id),
                sequence=0,
            )
            session.add(counter)
        counter.sequence += 1
        row = new_job(
            actor.subject,
            body.candidate_id,
            "ats",
            organization_id=str(body.organization_id),
            invitation_id=str(body.invitation_id),
            consent_id=str(body.consent_id),
        )
        row.sequence = counter.sequence
        session.add(row)
        return {"job_id": row.job_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "integration_ats_export",
        idempotency,
        body.model_dump(mode="json"),
        change,
        202,
        guard=guard,
        present=lambda session, result: view(session.get(Job, result["job_id"])),
    )


@router.get("/jobs/{job_id}", response_model=JobView)
def job(request: Request, actor: Actor, job_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(Job, str(job_id))
        if row is None or str(actor.subject) not in {row.candidate_id, row.actor_id}:
            raise HTTPException(404)
        fence(request, session, row.candidate_id, row.actor_id)
        if row.kind == "ats" and str(actor.subject) != row.candidate_id:
            actor.require("employer")
            membership(request, actor.subject, row.organization_id)
        else:
            actor.require("candidate")
        return view(row)


@internal_router.post("/{operation}", response_model=ExchangeReceipt)
def exchange(request: Request, body: ExchangeRequest, operation: str, signature: Signature = None):
    if operation != body.operation or operation not in {"permission", "status", "outcome"}:
        raise HTTPException(422)

    def handle(session):
        row = session.get(Job, str(body.request_id))
        if row is None or row.kind != "ats" or row.candidate_id != str(body.candidate_id):
            raise HTTPException(409)
        fence(request, session, row.candidate_id, row.actor_id)
        if operation == "outcome":
            if (
                body.payload
                or row.external_id is None
                or row.external_status is None
                or row.status != "completed"
            ):
                raise HTTPException(409)
            export_payload(request, row)
            return dict(
                job_id=row.job_id,
                candidate_id=row.candidate_id,
                organization_id=row.organization_id,
                invitation_id=row.invitation_id,
                actor_id=row.actor_id,
                external_id=row.external_id,
                status=row.external_status,
                sequence=row.status_sequence,
                revision=row.version,
                demo=True,
            )
        if operation == "permission":
            if (
                set(body.payload) != {"payload_digest", "lease_id", "read"}
                or type(body.payload["read"]) is not bool
            ):
                raise HTTPException(422)
            if body.payload["read"]:
                if row.status != "completed":
                    raise HTTPException(409)
            elif (
                row.status != "running"
                or row.lease_id != body.payload["lease_id"]
                or utc(row.lease_until) <= datetime.now(UTC)
            ):
                raise HTTPException(409)
            payload = export_payload(request, row)
            if payload_digest(payload) != body.payload["payload_digest"]:
                raise HTTPException(409, "Export changed during delivery")
            return {"allowed": True}
        export_payload(request, row)
        required = {"external_id", "status", "sequence", "organization_id"}
        if (
            set(body.payload) != required
            or body.payload["organization_id"] != row.organization_id
            or body.payload["status"] not in {"received", "interview", "offer", "hired", "rejected"}
        ):
            raise HTTPException(422)
        sequence = body.payload["sequence"]
        if type(sequence) is not int or sequence < 1:
            raise HTTPException(422)
        external_id = str(UUID(body.payload["external_id"]))
        existing = session.scalar(
            select(ATSStatusReceipt).where(
                ATSStatusReceipt.job_id == row.job_id, ATSStatusReceipt.sequence == sequence
            )
        )
        if existing:
            if existing.status != body.payload["status"] or row.external_id != external_id:
                raise HTTPException(409)
            return {"status": "duplicate"}
        if row.external_id and row.external_id != external_id:
            raise HTTPException(409)
        if sequence <= row.status_sequence:
            return {"status": "stale"}
        # Terminal statuses cannot be revived by a newer external message.
        if (
            row.external_status in {"hired", "rejected"}
            and row.external_status != body.payload["status"]
        ):
            raise HTTPException(409)
        row.external_id, row.external_status, row.status_sequence = (
            external_id,
            body.payload["status"],
            sequence,
        )
        row.version += 1
        session.add(
            ATSStatusReceipt(
                receipt_id=str(uuid4()),
                job_id=row.job_id,
                candidate_id=row.candidate_id,
                sequence=sequence,
                status=row.external_status,
            )
        )
        enqueue(
            session,
            EventEnvelope(
                producer="integration",
                event_type="integration.ats_status_changed.v1",
                aggregate_id=UUID(row.job_id),
                aggregate_version=row.version,
                correlation_id=request.state.trace_id,
                payload={
                    "candidate_id": body.candidate_id,
                    "organization_id": UUID(row.organization_id),
                    "job_id": UUID(row.job_id),
                },
            ),
        )
        return {"status": "applied"}

    return respond(
        request,
        body,
        signature,
        IntegrationNonce,
        {"hiring"} if operation == "outcome" else {"demo-ats"},
        handle,
    )


def run_one(request):
    engine = request.app.state.engine
    now = datetime.now(UTC)
    with Session(engine) as session:
        selected = session.scalar(
            select(Job)
            .where(
                ((Job.status == "pending") & (Job.available_at <= now))
                | ((Job.status == "running") & (Job.lease_until <= now))
            )
            .order_by(Job.available_at, Job.job_id)
            .limit(1)
        )
        if selected is None:
            return False
        refs = selected.job_id, selected.candidate_id, selected.actor_id
    with Session(engine) as session, session.begin():
        try:
            fence(request, session, refs[1], refs[2])
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            row = session.get(Job, refs[0])
            if row:
                row.status, row.error_code = "cancelled", "processing_restricted"
            return True
        row = session.scalar(select(Job).where(Job.job_id == refs[0]).with_for_update())
        if (
            row is None
            or row.status not in {"pending", "running"}
            or (row.status == "running" and utc(row.lease_until) > now)
        ):
            return False
        if row.attempts >= 3:
            row.status, row.error_code = "failed", "retry_exhausted"
            return True
        row.status, row.lease_id, row.lease_until = (
            "running",
            str(uuid4()),
            now + timedelta(seconds=60),
        )
        row.attempts, row.version = row.attempts + 1, row.version + 1
        session.flush()
        session.expunge(row)
    # No local subject/job lock is held during remote delivery or callbacks.
    external_id, error = None, None
    try:
        demo(request)
        exchange = request.app.state.exchange_access
        if row.kind == "sync":
            binding = exchange.call(
                "achievements",
                "connection",
                UUID(row.candidate_id),
                UUID(row.job_id),
                connection_id=row.connection_id,
            )
            if binding["adapter"] not in {"demo-fsp", "demo-codenrock"} or not binding["demo"]:
                raise HTTPException(409)
            data = exchange.call(
                binding["adapter"],
                "pull",
                UUID(row.candidate_id),
                UUID(row.job_id),
                external_account=binding["external_account"],
            )
            if set(data) != {"records", "demo"} or data["demo"] is not True:
                raise HTTPException(503)
            exchange.call(
                "achievements",
                "import",
                UUID(row.candidate_id),
                UUID(row.job_id),
                connection_id=row.connection_id,
                records=data["records"],
                connection_version=binding["version"],
            )
        else:
            payload = export_payload(request, row)
            from reverse_hr.audit_access import record_disclosure

            with Session(engine) as audit_session, audit_session.begin():
                record_disclosure(
                    audit_session,
                    request,
                    "ats_export",
                    row.job_id,
                    row.actor_id,
                    row.candidate_id,
                    row.organization_id,
                )
            result = exchange.call(
                "demo-ats",
                "push",
                UUID(row.candidate_id),
                UUID(row.job_id),
                delivery=payload,
                lease_id=row.lease_id,
            )
            if set(result) != {"external_id", "status", "sequence"} or result["status"] not in {
                "received",
                "interview",
                "offer",
                "hired",
                "rejected",
            }:
                raise HTTPException(503)
            external_id = str(UUID(result["external_id"]))
    except HTTPException as exc:
        error = (
            "permission_revoked"
            if exc.status_code in {401, 403, 404, 409}
            else "upstream_unavailable"
        )
    except Exception:
        error = "upstream_unavailable"
    with Session(engine) as session, session.begin():
        states = {
            subject: lock(session, IntegrationSubject, subject, allow_blocked=True)
            for subject in sorted({row.candidate_id, row.actor_id})
        }
        state = states[row.candidate_id]
        actor = states[row.actor_id]
        current = session.get(Job, row.job_id)
        if current is None or state.blocked or actor.blocked or current.lease_id != row.lease_id:
            return True
        current.version += 1
        current.lease_id, current.lease_until = None, None
        if error:
            current.error_code = error
            current.status = (
                "cancelled"
                if error == "permission_revoked"
                else "failed"
                if current.attempts >= 3
                else "pending"
            )
            current.available_at = datetime.now(UTC) + timedelta(seconds=5 * current.attempts)
        else:
            current.status, current.completed_at, current.error_code = (
                "completed",
                datetime.now(UTC),
                None,
            )
            if external_id:
                current.external_id = external_id
    return True


def process_deletion_request(session, event, request):
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = str(event.payload["candidate_id"])
        state = lock(session, IntegrationSubject, subject, allow_blocked=True)
        if state.request_id and state.request_id != str(event.payload["request_id"]):
            raise HTTPException(409)
        first = state.request_id is None
        state.blocked, state.request_id = True, str(event.payload["request_id"])
        rows = list(
            session.scalars(
                select(Job).where((Job.candidate_id == subject) | (Job.actor_id == subject))
            )
        )
        # Deleting an export author also erases their downstream deliveries.
        for candidate in sorted({subject} | {row.candidate_id for row in rows}):
            if request.app.state.settings.deployment_mode != "demo" and not any(
                item.kind == "ats" for item in rows
            ):
                continue
            receipt = request.app.state.exchange_access.call(
                "demo-ats", "erase", UUID(candidate), event.payload["request_id"], actor_id=subject
            )
            if receipt != {"erased": True}:
                raise HTTPException(503, "Downstream erasure not confirmed")
        ids = [row.job_id for row in rows]
        session.execute(delete(ATSStatusReceipt).where(ATSStatusReceipt.job_id.in_(ids)))
        session.execute(delete(Job).where(Job.job_id.in_(ids)))
        session.execute(delete(DeliveryCounter).where(DeliveryCounter.candidate_id == subject))
        session.execute(
            delete(IdempotencyRecord).where(
                (IdempotencyRecord.actor_id == subject)
                | IdempotencyRecord.response.contains(subject)
            )
        )
        session.execute(
            delete(Outbox).where(
                (Outbox.envelope["payload"]["candidate_id"].as_string() == subject)
                | Outbox.envelope["payload"]["job_id"].as_string().in_(ids),
                Outbox.envelope["event_type"].as_string() != "integration.data_deleted.v1",
            )
        )
        if first:
            enqueue(
                session,
                EventEnvelope(
                    producer="integration",
                    event_type="integration.data_deleted.v1",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    payload=event.payload,
                    aggregate_version=event.aggregate_version,
                ),
            )

    return consume_once(session, "integration.deletion", event, apply)


def process_consent_revoked(session, event, request):
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.consent_revoked.v1"
        or set(event.payload) != {"candidate_id", "consent_id"}
        or event.aggregate_id != event.payload["consent_id"]
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = str(event.payload["candidate_id"])
        lock(session, IntegrationSubject, subject, allow_blocked=True)
        rows = list(
            session.scalars(
                select(Job).where(
                    Job.candidate_id == subject, Job.consent_id == str(event.payload["consent_id"])
                )
            )
        )
        if rows:
            receipt = request.app.state.exchange_access.call(
                "demo-ats",
                "erase",
                event.payload["candidate_id"],
                event.event_id,
                actor_id=subject,
                permanent=False,
                job_ids=[row.job_id for row in rows],
            )
            if receipt != {"erased": True}:
                raise HTTPException(503, "Downstream erasure not confirmed")
        for row in rows:
            row.status, row.error_code, row.version = (
                "cancelled",
                "consent_revoked",
                row.version + 1,
            )
            row.lease_id, row.lease_until = None, None

    return consume_once(session, "integration.consent", event, apply)
