"""Independent demo ATS database and signed callback queue; no unguarded profile download."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.contracts.core import ContactView, Contract
from reverse_hr.contracts.market_contracts import CandidateCard
from reverse_hr.contracts.test_suites import digest
from reverse_hr.protocols.exchange import ExchangeReceipt, ExchangeRequest, respond
from reverse_hr.protocols.market_access import Signature
from reverse_hr.protocols.market_state import NonceColumns, SubjectColumns, lock
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord


class DemoATSBase(DeclarativeBase):
    pass


class ATSSubject(SubjectColumns, DemoATSBase):
    __tablename__ = "demo_ats_subjects"


class ATSNonce(NonceColumns, DemoATSBase):
    __tablename__ = "demo_ats_nonces"


class ATSCandidate(DemoATSBase):
    __tablename__ = "demo_ats_candidates"
    __table_args__ = (UniqueConstraint("candidate_id", "organization_id"),)
    external_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    job_id: Mapped[str] = mapped_column(String(36))
    delivery_sequence: Mapped[int]
    status_sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))
    payload: Mapped[dict] = mapped_column(JSON)
    payload_digest: Mapped[str] = mapped_column(String(64))
    version: Mapped[int]


class ATSDelivery(DemoATSBase):
    __tablename__ = "demo_ats_deliveries"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    external_id: Mapped[str] = mapped_column(String(36), index=True)
    payload_digest: Mapped[str] = mapped_column(String(64))


class ATSCallback(DemoATSBase):
    __tablename__ = "demo_ats_callbacks"
    callback_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    __table_args__ = (UniqueConstraint("job_id", "sequence"),)
    job_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36))
    external_id: Mapped[str] = mapped_column(String(36))
    sequence: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))
    state: Mapped[str] = mapped_column(String(24))
    attempts: Mapped[int]
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Delivery(Contract):
    job_id: UUID
    candidate_id: UUID
    organization_id: UUID
    actor_id: UUID
    sequence: int = Field(strict=True, ge=1)
    demo: Literal[True]
    profile: CandidateCard
    contacts: ContactView


class StatusCommand(Contract):
    status: Literal["interview", "offer", "hired", "rejected"]


router = APIRouter(tags=["demo-ats"])
NEXT = {
    "received": {"interview", "rejected"},
    "interview": {"offer", "rejected"},
    "offer": {"hired", "rejected"},
}


def permission(request, row, *, read=False, lease_id=None):
    request.app.state.exchange_access.call(
        "integration",
        "permission",
        UUID(row.candidate_id),
        UUID(row.job_id),
        payload_digest=row.payload_digest,
        lease_id=lease_id,
        read=read,
    )


def guards(request, session, candidate, actor):
    if request.app.state.settings.deployment_mode != "demo":
        raise HTTPException(409)
    for subject in sorted({str(candidate), str(actor)}):
        lock(session, ATSSubject, subject)
        request.app.state.processing_access.check(UUID(subject))


def callback(session, row):
    session.add(
        ATSCallback(
            callback_id=str(uuid4()),
            job_id=row.job_id,
            candidate_id=row.candidate_id,
            actor_id=row.actor_id,
            organization_id=row.organization_id,
            external_id=row.external_id,
            sequence=row.status_sequence,
            status=row.status,
            state="pending",
            attempts=0,
            available_at=datetime.now(UTC),
        )
    )


@router.post("/internal/v1/exchange/{operation}", response_model=ExchangeReceipt)
def exchange(request: Request, body: ExchangeRequest, operation: str, signature: Signature = None):
    if operation != body.operation or operation not in {"push", "erase"}:
        raise HTTPException(422)
    # Check authenticity before making any upstream permission request.
    # The mutation handler runs only after the same signature/nonce check in respond.
    from reverse_hr.protocols.exchange import context
    from reverse_hr.shared.event_transport import Signatures
    from reverse_hr.shared.signing import fresh, verify

    signatures = getattr(
        request.app.state, "exchange_signatures", None
    ) or Signatures.from_settings(request.app.state.settings)
    try:
        if signature is None or not fresh(body.issued_at) or body.requester != "integration":
            raise ValueError("Unauthorized")
        verify(
            signatures, "integration", signature, context("demo-ats", operation, "request"), body
        )
    except Exception as exc:
        raise HTTPException(401) from exc
    delivery = None
    if operation == "push":
        if set(body.payload) != {"delivery", "lease_id"}:
            raise HTTPException(422)
        delivery = Delivery.model_validate(body.payload["delivery"])
        if (
            delivery.job_id != body.request_id
            or delivery.candidate_id != body.candidate_id
            or delivery.profile.candidate_id != body.candidate_id
            or delivery.contacts.candidate_id != body.candidate_id
            or delivery.contacts.organization_id != delivery.organization_id
        ):
            raise HTTPException(409)
        # No ATS lock is held while checking Integration's fresh disclosure proof.
        request.app.state.exchange_access.call(
            "integration",
            "permission",
            body.candidate_id,
            body.request_id,
            payload_digest=digest(delivery),
            lease_id=body.payload["lease_id"],
            read=False,
        )

    def handle(session):
        if operation == "erase":
            permanent = body.payload.get("permanent", True)
            actor = body.payload.get("actor_id")
            if (
                type(permanent) is not bool
                or actor is None
                or set(body.payload) - {"actor_id", "permanent", "job_ids"}
            ):
                raise HTTPException(422)
            actor = str(UUID(actor))
            target = lock(
                session, ATSSubject, actor if permanent else body.candidate_id, allow_blocked=True
            )
            if permanent:
                target.blocked = True
            ids = body.payload.get("job_ids")
            rows = list(
                session.scalars(
                    select(ATSCandidate).where(ATSCandidate.candidate_id == str(body.candidate_id))
                )
            )
            for row in rows:
                if (ids is not None and row.job_id in ids) or (
                    ids is None and (str(body.candidate_id) == actor or row.actor_id == actor)
                ):
                    session.delete(row)
            for table in (ATSDelivery, ATSCallback):
                query = delete(table).where(table.candidate_id == str(body.candidate_id))
                if ids is not None:
                    query = query.where(table.job_id.in_(ids))
                elif str(body.candidate_id) != actor:
                    query = query.where(table.actor_id == actor)
                session.execute(query)
            session.execute(
                delete(IdempotencyRecord).where(
                    (IdempotencyRecord.actor_id == actor)
                    | IdempotencyRecord.response.contains(str(body.candidate_id))
                )
            )
            return {"erased": True}
        guards(request, session, body.candidate_id, delivery.actor_id)
        fingerprint = digest(delivery)
        existing = session.get(ATSDelivery, str(body.request_id))
        if existing:
            if existing.payload_digest != fingerprint:
                raise HTTPException(409)
            row = session.get(ATSCandidate, existing.external_id)
            if row is None:
                raise HTTPException(409)
            return {
                "external_id": row.external_id,
                "status": row.status,
                "sequence": row.status_sequence,
            }
        row = session.scalar(
            select(ATSCandidate).where(
                ATSCandidate.candidate_id == str(body.candidate_id),
                ATSCandidate.organization_id == str(delivery.organization_id),
            )
        )
        if row is not None and delivery.sequence <= row.delivery_sequence:
            raise HTTPException(409, "Stale ATS delivery")
        if row is None:
            row = ATSCandidate(
                external_id=str(uuid4()),
                candidate_id=str(body.candidate_id),
                organization_id=str(delivery.organization_id),
                status="received",
                status_sequence=0,
                version=0,
            )
            session.add(row)
        row.actor_id, row.job_id, row.delivery_sequence = (
            str(delivery.actor_id),
            str(body.request_id),
            delivery.sequence,
        )
        row.payload, row.payload_digest = delivery.model_dump(mode="json"), fingerprint
        row.version, row.status_sequence = row.version + 1, row.status_sequence + 1
        session.add(
            ATSDelivery(
                job_id=str(body.request_id),
                candidate_id=row.candidate_id,
                actor_id=row.actor_id,
                external_id=row.external_id,
                payload_digest=fingerprint,
            )
        )
        callback(session, row)
        return {
            "external_id": row.external_id,
            "status": row.status,
            "sequence": row.status_sequence,
        }

    return respond(request, body, signature, ATSNonce, {"integration"}, handle)


@router.get("/v1/ats/candidates/{external_id}")
def get_candidate(request: Request, actor: Actor, external_id: UUID):
    actor.require("employer")
    with Session(request.app.state.engine) as session:
        row = session.get(ATSCandidate, str(external_id))
        if row is None:
            raise HTTPException(404)
        request.app.state.market_access.require(
            "employer",
            "membership",
            candidate_id=actor.subject,
            actor_id=actor.subject,
            organization_id=UUID(row.organization_id),
        )
        permission(request, row, read=True)
        before = row.version
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(ATSCandidate, str(external_id))
        if row is None or row.version != before:
            raise HTTPException(409)
        guards(request, session, row.candidate_id, actor.subject)
        return dict(
            external_id=row.external_id,
            version=row.version,
            status=row.status,
            demo=True,
            profile=row.payload["profile"],
            contacts=row.payload["contacts"],
        )


@router.post("/v1/ats/candidates/{external_id}/status")
def status(
    request: Request,
    actor: Actor,
    external_id: UUID,
    body: StatusCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    get_candidate(request, actor, external_id)

    def guard(session):
        row = session.get(ATSCandidate, str(external_id))
        if row is None:
            raise HTTPException(404)
        guards(request, session, row.candidate_id, actor.subject)
        request.app.state.market_access.require(
            "employer",
            "membership",
            candidate_id=actor.subject,
            actor_id=actor.subject,
            organization_id=UUID(row.organization_id),
        )

    def change(session):
        row = session.get(ATSCandidate, str(external_id))
        if row.version != int(if_match.strip('"')) or body.status not in NEXT.get(
            row.status, set()
        ):
            raise HTTPException(409)
        row.status, row.version, row.status_sequence = (
            body.status,
            row.version + 1,
            row.status_sequence + 1,
        )
        callback(session, row)
        return {"external_id": row.external_id, "status": row.status, "version": row.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        "demo_ats_status:" + str(external_id),
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
        change,
        guard=guard,
    )


def run_callback(request):
    now = datetime.now(UTC)
    with Session(request.app.state.engine) as session:
        selected = session.scalar(
            select(ATSCallback)
            .where(ATSCallback.state == "pending", ATSCallback.available_at <= now)
            .order_by(ATSCallback.available_at, ATSCallback.callback_id)
            .limit(1)
        )
        if selected is None:
            return False
        key, candidate, actor = selected.callback_id, selected.candidate_id, selected.actor_id
    with Session(request.app.state.engine) as session, session.begin():
        for subject in sorted({candidate, actor}):
            lock(session, ATSSubject, subject, allow_blocked=True)
        row = session.scalar(
            select(ATSCallback).where(ATSCallback.callback_id == key).with_for_update()
        )
        if (
            row is None
            or row.state != "pending"
            or (
                row.available_at.replace(tzinfo=UTC)
                if row.available_at.tzinfo is None
                else row.available_at
            )
            > now
        ):
            return False
        row.attempts += 1
        # A retry lease is committed before remote I/O; crashes retry with the same sequence.
        row.available_at = now + timedelta(seconds=30)
        session.flush()
        session.expunge(row)
    error = None
    try:
        request.app.state.exchange_access.call(
            "integration",
            "status",
            UUID(row.candidate_id),
            UUID(row.job_id),
            external_id=row.external_id,
            status=row.status,
            sequence=row.sequence,
            organization_id=row.organization_id,
        )
    except HTTPException as exc:
        error = (
            "cancelled"
            if exc.status_code in {401, 403, 404, 409}
            else "failed"
            if row.attempts >= 5
            else "pending"
        )
    except Exception:
        error = "failed" if row.attempts >= 5 else "pending"
    with Session(request.app.state.engine) as session, session.begin():
        current = session.get(ATSCallback, key)
        if current and current.attempts == row.attempts:
            current.state = error or "delivered"
            current.available_at = datetime.now(UTC) + timedelta(seconds=5 * row.attempts)
    return True
