"""Finite-retention, signed and tamper-evident audit evidence.

The global chain authenticates received content hashes. Private searchable
projections and original proofs can be erased without rewriting chain evidence.
No contact values, documents or user-authored text are accepted in the journal.
"""

import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import JSON, DateTime, Integer, String, Text, cast, delete, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.db import Outbox, enqueue

ZERO = "0" * 64
CHAIN_CONTEXT = b"reverse-hr.audit-chain.v1\0"
REDACTION_CONTEXT = b"reverse-hr.audit-redaction.v1\0"
SUBJECT_KEYS = {
    "actor_id",
    "author_id",
    "creator_id",
    "candidate_id",
    "recipient_id",
    "reviewer_id",
    "subject_id",
    "owner_id",
    "member_id",
}


class AuditBase(DeclarativeBase):
    pass


class ChainHead(AuditBase):
    __tablename__ = "audit_chain_head"
    chain_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sequence: Mapped[int]
    digest: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(128))


class AuditEntry(AuditBase):
    __tablename__ = "audit_entries"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), unique=True)
    producer: Mapped[str] = mapped_column(String(50), index=True)
    event_type: Mapped[str] = mapped_column(String(120), index=True)
    aggregate_id: Mapped[str | None] = mapped_column(String(36), index=True)
    aggregate_version: Mapped[int]
    subjects: Mapped[list] = mapped_column(JSON)
    references: Mapped[dict] = mapped_column(JSON)
    original_body: Mapped[str | None] = mapped_column(Text)
    original_signature: Mapped[str] = mapped_column(String(128))
    proof_kind: Mapped[str] = mapped_column(String(16))
    content_digest: Mapped[str] = mapped_column(String(64))
    receipt_digest: Mapped[str] = mapped_column(String(64))
    projection_digest: Mapped[str] = mapped_column(String(64))
    previous_digest: Mapped[str] = mapped_column(String(64))
    chain_digest: Mapped[str] = mapped_column(String(64))
    chain_signature: Mapped[str] = mapped_column(String(128))
    delivery: Mapped[str] = mapped_column(String(24))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    erased: Mapped[bool]
    redaction_signature: Mapped[str | None] = mapped_column(String(128))
    redaction_reason: Mapped[str | None] = mapped_column(String(16))
    redacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Stream(AuditBase):
    __tablename__ = "audit_streams"
    producer: Mapped[str] = mapped_column(String(50), primary_key=True)
    aggregate_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ErasedSubject(AuditBase):
    __tablename__ = "audit_erased_subjects"
    subject_digest: Mapped[str] = mapped_column(String(64), primary_key=True)
    request_digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditNonce(AuditBase):
    __tablename__ = "audit_nonces"
    owner: Mapped[str] = mapped_column(String(50), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def digest(raw):
    return hashlib.sha256(raw if isinstance(raw, bytes) else raw.encode()).hexdigest()


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def retention(settings):
    days = getattr(settings, "audit_retention_days", 365)
    if not 1 <= days <= 3650:
        raise ValueError("Audit retention must be between one and 3650 days")
    return timedelta(days=days)


def chain_message(sequence, previous, content, receipt):
    return CHAIN_CONTEXT + encode(
        {
            "sequence": sequence,
            "previous_digest": previous,
            "content_digest": content,
            "receipt_digest": receipt,
        }
    )


def receipt_metadata(row):
    return {
        "event_id": row.event_id,
        "producer": row.producer,
        "event_type": row.event_type,
        "aggregate_version": row.aggregate_version,
        "proof_kind": row.proof_kind,
        "original_signature": row.original_signature,
        "delivery": row.delivery,
        "occurred_at": utc(row.occurred_at).isoformat(),
        "received_at": utc(row.received_at).isoformat(),
        "expires_at": utc(row.expires_at).isoformat(),
        "projection_digest": row.projection_digest,
    }


def projection_hash(aggregate, subjects, references):
    return digest(
        encode({"aggregate_id": aggregate, "subjects": subjects, "references": references})
    )


def serialize_chain(session):
    # UPDATE acquires an actual write lock on SQLite too; SELECT FOR UPDATE alone
    # does not. The singleton is seeded by migration, never lazily created.
    changed = session.execute(
        update(ChainHead).where(ChainHead.chain_id == 1).values(sequence=ChainHead.sequence)
    ).rowcount
    if changed != 1:
        raise HTTPException(503, "Audit migration unavailable")
    return session.scalar(
        select(ChainHead)
        .where(ChainHead.chain_id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def redaction_message(row):
    return REDACTION_CONTEXT + encode(
        {
            "sequence": row.sequence,
            "chain_digest": row.chain_digest,
            "reason": row.redaction_reason,
            "at": utc(row.redacted_at).isoformat(),
        }
    )


def redact(row, signatures, reason, now):
    row.subjects, row.references, row.aggregate_id, row.original_body, row.erased = (
        [],
        {},
        None,
        None,
        True,
    )
    row.redaction_reason, row.redacted_at = reason, now
    row.redaction_signature = base64.b64encode(
        signatures.private.sign(redaction_message(row))
    ).decode()


def verify_entry(row, signatures):
    try:
        message = chain_message(
            row.sequence, row.previous_digest, row.content_digest, row.receipt_digest
        )
        signatures.public["audit"].verify(
            base64.b64decode(row.chain_signature, validate=True), message
        )
        if (
            digest(message) != row.chain_digest
            or digest(encode(receipt_metadata(row))) != row.receipt_digest
        ):
            raise ValueError()
        if row.erased:
            if (
                row.original_body is not None
                or row.subjects
                or row.references
                or row.aggregate_id is not None
            ):
                raise ValueError()
            if row.redaction_reason not in {"privacy", "retention", "processing"}:
                raise ValueError()
            signatures.public["audit"].verify(
                base64.b64decode(row.redaction_signature, validate=True), redaction_message(row)
            )
        elif (
            row.original_body is None
            or digest(row.original_body) != row.content_digest
            or projection_hash(row.aggregate_id, row.subjects, row.references)
            != row.projection_digest
        ):
            raise ValueError()
    except Exception as exc:
        raise IntegrityFailure() from exc


class IntegrityFailure(HTTPException):
    def __init__(self):
        super().__init__(409, "Audit evidence verification failed")


def runtime_signatures(settings, explicit):
    if explicit is not None:
        return explicit
    from reverse_hr.shared.event_transport import Signatures

    return Signatures.from_settings(settings)


def append(
    session,
    event,
    body,
    signature,
    signatures,
    settings,
    *,
    proof_kind="event",
    blocked=False,
    now=None,
):
    now = now or datetime.now(UTC)
    if event.occurred_at.tzinfo is None or event.occurred_at > now + timedelta(minutes=2):
        raise HTTPException(409)
    head = serialize_chain(session)
    if head.sequence:
        boundary = session.get(AuditEntry, head.sequence)
        if (
            boundary is None
            or boundary.chain_digest != head.digest
            or boundary.chain_signature != head.signature
        ):
            raise IntegrityFailure()
        verify_entry(boundary, signatures)
    content = digest(body)
    prior = session.scalar(select(AuditEntry).where(AuditEntry.event_id == str(event.event_id)))
    if prior:
        if (
            prior.content_digest != content
            or prior.original_signature != signature
            or prior.proof_kind != proof_kind
        ):
            raise HTTPException(409, "Conflicting audit replay")
        return prior
    # Ancient broker backfill is intentionally ignored once the retention window
    # has elapsed, including after replay/tombstone records have been purged.
    if event.occurred_at < now - retention(settings):
        return None
    subjects = sorted({str(value) for key, value in event.payload.items() if key in SUBJECT_KEYS})
    erased = blocked or any(
        session.get(ErasedSubject, digest(str(value))) for value in event.payload.values()
    )
    aggregate = digest(event.producer + ":" + str(event.aggregate_id))
    stream = session.get(Stream, (event.producer, aggregate))
    if stream is None:
        delivery = "initial" if event.aggregate_version == 1 else "gap"
        stream = Stream(
            producer=event.producer,
            aggregate_digest=aggregate,
            version=event.aggregate_version,
            expires_at=now + retention(settings),
        )
        session.add(stream)
    else:
        delivery = (
            "stale"
            if event.aggregate_version < stream.version
            else "same_version"
            if event.aggregate_version == stream.version
            else "gap"
            if event.aggregate_version > stream.version + 1
            else "next"
        )
        stream.version = max(stream.version, event.aggregate_version)
        stream.expires_at = now + retention(settings)
    sequence = head.sequence + 1
    previous = head.digest
    references = {key: str(value) for key, value in event.payload.items()}
    projection_digest = projection_hash(str(event.aggregate_id), subjects, references)
    row = AuditEntry(
        sequence=sequence,
        event_id=str(event.event_id),
        producer=event.producer,
        event_type=event.event_type,
        aggregate_id=None if erased else str(event.aggregate_id),
        aggregate_version=event.aggregate_version,
        subjects=[] if erased else subjects,
        references={} if erased else references,
        original_body=None if erased else body.decode(),
        original_signature=signature,
        proof_kind=proof_kind,
        content_digest=content,
        receipt_digest=ZERO,
        projection_digest=projection_digest,
        previous_digest=previous,
        chain_digest=ZERO,
        chain_signature="",
        delivery=delivery,
        received_at=now,
        occurred_at=event.occurred_at,
        expires_at=now + retention(settings),
        erased=erased,
    )
    row.receipt_digest = digest(encode(receipt_metadata(row)))
    message = chain_message(sequence, previous, content, row.receipt_digest)
    row.chain_digest = digest(message)
    row.chain_signature = base64.b64encode(signatures.private.sign(message)).decode()
    if erased:
        redact(row, signatures, "processing" if blocked else "privacy", now)
    session.add(row)
    head.sequence, head.digest, head.signature = sequence, row.chain_digest, row.chain_signature
    session.flush()
    return row


def erase_subject(session, event, settings, *, now=None, signatures=None):
    now = now or datetime.now(UTC)
    signatures = runtime_signatures(settings, signatures)
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
    ):
        raise HTTPException(409)
    serialize_chain(session)
    subject = str(event.payload["candidate_id"])
    key = digest(subject)
    request_hash = digest(str(event.payload["request_id"]))
    tombstone = session.get(ErasedSubject, key)
    if tombstone and tombstone.request_digest != request_hash:
        raise HTTPException(409)
    first = tombstone is None
    if first:
        session.add(
            ErasedSubject(
                subject_digest=key,
                request_digest=request_hash,
                expires_at=now + retention(settings),
            )
        )
    for row in session.scalars(select(AuditEntry)):
        if (
            subject in row.subjects
            or subject in row.references.values()
            or subject == row.aggregate_id
        ):
            redact(row, signatures, "privacy", now)
    # Signed audit read receipts also contain actor references; do not retain
    # pending historical receipts that would recreate the erased projection.
    session.execute(
        delete(Outbox).where(
            cast(Outbox.envelope, Text).contains(subject),
            Outbox.envelope["event_type"].as_string() != "audit.data_deleted.v1",
        )
    )
    if first:
        enqueue(
            session,
            EventEnvelope(
                producer="audit",
                event_type="audit.data_deleted.v1",
                correlation_id=event.correlation_id,
                aggregate_id=event.aggregate_id,
                aggregate_version=1,
                payload=event.payload,
            ),
        )
    return first


def verify_chain(session, signatures):
    head = serialize_chain(session)
    rows = session.scalars(
        select(AuditEntry).order_by(AuditEntry.sequence).execution_options(yield_per=100)
    )
    previous = None
    first_sequence = 0
    last = None
    for row in rows:
        if not first_sequence:
            first_sequence = row.sequence
        verify_entry(row, signatures)
        message = chain_message(
            row.sequence, row.previous_digest, row.content_digest, row.receipt_digest
        )
        try:
            signatures.public["audit"].verify(
                base64.b64decode(row.chain_signature, validate=True), message
            )
            if (
                digest(message) != row.chain_digest
                or digest(encode(receipt_metadata(row))) != row.receipt_digest
            ):
                raise ValueError()
            if last is not None and (
                row.sequence != last.sequence + 1 or row.previous_digest != previous
            ):
                raise ValueError()
            if row.original_body is not None:
                if digest(row.original_body) != row.content_digest:
                    raise ValueError()
                if row.proof_kind == "event":
                    signatures.verify(
                        row.original_body.encode(),
                        {"hr-producer": row.producer, "hr-signature": row.original_signature},
                        row.event_id,
                    )
                else:
                    from reverse_hr.protocols.audit_access import REQUEST_CONTEXT, DisclosureRequest
                    from reverse_hr.shared.signing import verify

                    proof = DisclosureRequest.model_validate_json(row.original_body)
                    verify(signatures, row.producer, row.original_signature, REQUEST_CONTEXT, proof)
            elif not row.erased:
                raise ValueError()
            if (
                not row.erased
                and projection_hash(row.aggregate_id, row.subjects, row.references)
                != row.projection_digest
            ):
                raise ValueError()
        except Exception as exc:
            raise HTTPException(409, "Audit chain verification failed") from exc
        previous, last = row.chain_digest, row
    if last and (
        last.sequence != head.sequence
        or last.chain_digest != head.digest
        or last.chain_signature != head.signature
    ):
        raise HTTPException(409, "Audit head verification failed")
    if last is None and head.sequence:
        # Retention cleanup deliberately keeps the signed boundary record.
        raise HTTPException(409, "Missing audit boundary")
    return {
        "verified": True,
        "first_sequence": first_sequence,
        "last_sequence": head.sequence,
        "head_digest": head.digest,
        "head_signature": head.signature,
    }


def prune(session, settings, *, now=None, signatures=None):
    now = now or datetime.now(UTC)
    signatures = runtime_signatures(settings, signatures)
    head = serialize_chain(session)
    # Keep one proof-only signed boundary so tail deletion is detectable while
    # all personal projections/original bytes obey finite expiry.
    rows = list(session.scalars(select(AuditEntry).order_by(AuditEntry.sequence)))
    prefix = True
    count = 0
    for row in rows:
        expired = utc(row.expires_at) <= now
        if expired:
            if not row.erased or row.original_body or row.subjects or row.references:
                count += 1
            if not row.erased:
                redact(row, signatures, "retention", now)
            if prefix and row.sequence != head.sequence:
                session.delete(row)
        else:
            prefix = False
    session.execute(delete(Stream).where(Stream.expires_at <= now))
    session.execute(delete(ErasedSubject).where(ErasedSubject.expires_at <= now))
    session.execute(delete(AuditNonce).where(AuditNonce.expires_at <= now))
    session.execute(
        delete(Outbox).where(
            Outbox.status == "published", Outbox.published_at <= now - retention(settings)
        )
    )
    return count


def safe_subject_entries(session, subject, *, after=0, limit=50):
    """Privacy export: own involvement only, with no other person's identifiers."""
    result = []
    scanned = list(
        session.scalars(
            select(AuditEntry)
            .where(AuditEntry.sequence > after)
            .order_by(AuditEntry.sequence)
            .limit(500)
        )
    )
    cursor = after
    for row in scanned:
        cursor = row.sequence
        if (
            not row.erased
            and utc(row.expires_at) > datetime.now(UTC)
            and str(subject) in row.subjects
        ):
            result.append(
                {
                    "entry_id": row.event_id,
                    "action": row.event_type,
                    "producer": row.producer,
                    "occurred_at": utc(row.occurred_at).isoformat(),
                    "delivery": row.delivery,
                }
            )
            if len(result) == limit:
                break
    return result, cursor if scanned else None


router = APIRouter(prefix="/v1/audit", tags=["audit"])


def request_signatures(request):
    explicit = getattr(request.app.state, "audit_signatures", None)
    return explicit if explicit is not None else request.app.state.processing_access.signatures


def authorize(request, actor):
    actor.require("audit_reviewer", mfa=True)
    request.app.state.processing_access.check(actor.subject)


def journal_view(request, actor, row):
    verify_entry(row, request_signatures(request))
    if utc(row.expires_at) <= datetime.now(UTC):
        raise HTTPException(404)
    if row.erased or str(actor.subject) in row.subjects:
        raise HTTPException(403)
    for subject in row.subjects:
        request.app.state.processing_access.check(UUID(subject))
    return {
        "entry_id": row.event_id,
        "sequence": row.sequence,
        "producer": row.producer,
        "event_type": row.event_type,
        "aggregate_id": row.aggregate_id,
        "aggregate_version": row.aggregate_version,
        "references": row.references,
        "delivery": row.delivery,
        "occurred_at": utc(row.occurred_at),
        "received_at": utc(row.received_at),
        "content_digest": row.content_digest,
        "chain_digest": row.chain_digest,
        "chain_signature": row.chain_signature,
    }


def read_receipt(session, request, actor, resource=None):
    payload = {"actor_id": actor.subject}
    if resource:
        payload["resource_id"] = UUID(resource)
    enqueue(
        session,
        EventEnvelope(
            producer="audit",
            event_type="audit.journal_read.v1",
            correlation_id=request.state.trace_id,
            aggregate_id=uuid4(),
            aggregate_version=1,
            payload=payload,
        ),
    )


@router.get("/entries")
def search(
    request: Request,
    response: Response,
    actor: Actor,
    by_actor: UUID | None = None,
    by_case: UUID | None = None,
    producer: str | None = None,
    after: int = 0,
    occurred_from: datetime | None = None,
    occurred_to: datetime | None = None,
):
    authorize(request, actor)
    if after < 0 or (producer and len(producer) > 50):
        raise HTTPException(422)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(AuditEntry).where(AuditEntry.sequence > after)
        if producer:
            query = query.where(AuditEntry.producer == producer)
        if occurred_from:
            if occurred_from.tzinfo is None:
                raise HTTPException(422)
            query = query.where(AuditEntry.occurred_at >= occurred_from)
        if occurred_to:
            if occurred_to.tzinfo is None or (occurred_from and occurred_to < occurred_from):
                raise HTTPException(422)
            query = query.where(AuditEntry.occurred_at <= occurred_to)
        scanned = list(session.scalars(query.order_by(AuditEntry.sequence).limit(51)))
        rows = scanned[:50]
        if len(scanned) > 50:
            response.headers["X-HR-Next-Cursor"] = str(rows[-1].sequence)
        result = []
        for row in rows:
            if by_actor and str(by_actor) not in row.subjects:
                continue
            if (
                by_case
                and str(by_case) != row.aggregate_id
                and str(by_case) not in row.references.values()
            ):
                continue
            try:
                result.append(journal_view(request, actor, row))
            except HTTPException as exc:
                if isinstance(exc, IntegrityFailure):
                    raise
                if exc.status_code in {403, 404, 409}:
                    continue
                raise
        read_receipt(session, request, actor)
        return result


@router.get("/entries/{event_id}")
def detail(request: Request, actor: Actor, event_id: UUID):
    authorize(request, actor)
    with Session(request.app.state.engine) as session, session.begin():
        row = session.scalar(select(AuditEntry).where(AuditEntry.event_id == str(event_id)))
        if row is None:
            raise HTTPException(404)
        result = journal_view(request, actor, row)
        read_receipt(session, request, actor, row.event_id)
        return result


@router.get("/verify")
def verification(request: Request, actor: Actor):
    authorize(request, actor)
    with Session(request.app.state.engine) as session, session.begin():
        result = verify_chain(session, request_signatures(request))
        read_receipt(session, request, actor)
        return result


def subject_export_records(session, subject):
    """Deterministic Privacy-owned export adapter; no other subject's metadata."""
    for row in session.scalars(
        select(AuditEntry)
        .where(
            AuditEntry.erased.is_(False),
            cast(AuditEntry.subjects, Text).contains(str(subject)),
            AuditEntry.expires_at > datetime.now(UTC),
        )
        .order_by(AuditEntry.sequence)
        .execution_options(yield_per=64)
    ):
        if (
            not row.erased
            and utc(row.expires_at) > datetime.now(UTC)
            and str(subject) in row.subjects
        ):
            yield {
                "table": "audit_entries",
                "key": str(row.sequence),
                "data": {
                    "entry_id": row.event_id,
                    "action": row.event_type,
                    "producer": row.producer,
                    "occurred_at": utc(row.occurred_at).isoformat(),
                    "delivery": row.delivery,
                },
            }


internal_router = APIRouter(prefix="/internal/v1/audit", tags=["internal-audit"])


def allowed_disclosure(body):
    owners = {
        "contacts": {"hiring", "candidate"},
        "resume_pdf": {"candidate"},
        "ats_export": {"integration", "demo-ats", "hiring"},
        "external_delivery": {"integration", "notification", "demo-ats"},
    }
    if body.owner not in owners[body.kind]:
        raise HTTPException(403)


# Types are imported after defining AuditBase to keep transport/app wiring lazy.
from reverse_hr.protocols.audit_access import DisclosureReceipt, DisclosureRequest  # noqa: E402
from reverse_hr.protocols.market_access import Signature  # noqa: E402


@internal_router.post("/disclosures", response_model=DisclosureReceipt)
def disclosure(request: Request, response: Response, body: DisclosureRequest, signature: Signature):
    from reverse_hr.protocols.audit_access import (
        REQUEST_CONTEXT,
        RESPONSE_CONTEXT,
        disclosure_event,
    )
    from reverse_hr.shared.signing import canonical, fresh, sign, verify

    allowed_disclosure(body)
    if not fresh(body.issued_at):
        raise HTTPException(409)
    signatures = request_signatures(request)
    try:
        verify(signatures, body.owner, signature, REQUEST_CONTEXT, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    for subject in {body.actor_id, body.candidate_id} | (
        {body.recipient_id} if body.recipient_id else set()
    ):
        request.app.state.processing_access.check(subject)
    with Session(request.app.state.engine) as session, session.begin():
        serialize_chain(session)
        if session.get(AuditNonce, (body.owner, str(body.nonce))):
            raise HTTPException(409)
        session.add(
            AuditNonce(
                owner=body.owner,
                nonce=str(body.nonce),
                expires_at=datetime.now(UTC) + timedelta(minutes=2),
            )
        )
        prior = session.scalar(select(AuditEntry).where(AuditEntry.event_id == str(body.effect_id)))
        if prior:
            if prior.original_body is None or prior.proof_kind != "disclosure":
                raise HTTPException(409)
            original = DisclosureRequest.model_validate_json(prior.original_body)
            mutable = {"nonce", "issued_at"}
            if original.model_dump(exclude=mutable) != body.model_dump(exclude=mutable):
                raise HTTPException(409)
            row = prior
        else:
            row = append(
                session,
                disclosure_event(body),
                canonical(body),
                signature,
                signatures,
                request.app.state.settings,
                proof_kind="disclosure",
            )
        if row is None or row.erased:
            raise HTTPException(409)
        receipt = DisclosureReceipt(
            **body.model_dump(), entry_id=UUID(row.event_id), content_digest=row.content_digest
        )
        response.headers["X-HR-Signature"] = sign(signatures, RESPONSE_CONTEXT, receipt)
        return receipt


def run_retention_one(engine, settings, *, now=None, signatures=None):
    with Session(engine) as session, session.begin():
        return bool(prune(session, settings, now=now, signatures=signatures))
