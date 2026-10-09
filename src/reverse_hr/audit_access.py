"""Owner outbox disclosure receipts and signed external delivery receipts."""

from datetime import datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field

from reverse_hr.contracts import Contract
from reverse_hr.db import enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import canonical, sign

REQUEST_CONTEXT = b"reverse-hr.audit-disclosure-request.v1\0"
RESPONSE_CONTEXT = b"reverse-hr.audit-disclosure-response.v1\0"
Kind = Literal["contacts", "resume_pdf", "ats_export", "external_delivery"]


class DisclosureRequest(Contract):
    owner: str = Field(min_length=1, max_length=50, pattern=r"^[a-z][a-z0-9-]*$")
    kind: Kind
    effect_id: UUID
    resource_id: UUID
    actor_id: UUID
    candidate_id: UUID
    organization_id: UUID | None = None
    recipient_id: UUID | None = None
    nonce: UUID
    issued_at: datetime


class DisclosureReceipt(DisclosureRequest):
    entry_id: UUID
    content_digest: str = Field(pattern=r"^[0-9a-f]{64}$")


def disclosure_event(body):
    refs = {
        "resource_id": body.resource_id,
        "actor_id": body.actor_id,
        "candidate_id": body.candidate_id,
    }
    if body.organization_id:
        refs["organization_id"] = body.organization_id
    if body.recipient_id:
        refs["recipient_id"] = body.recipient_id
    return EventEnvelope(
        event_id=body.effect_id,
        producer=body.owner,
        event_type=f"{body.owner}.{body.kind}_disclosed.v1",
        occurred_at=body.issued_at,
        correlation_id=body.nonce,
        aggregate_id=body.resource_id,
        aggregate_version=1,
        payload=refs,
    )


def record_disclosure(
    session,
    request,
    kind: Kind,
    resource_id,
    actor_id,
    candidate_id,
    organization_id=None,
    *,
    recipient_id=None,
    effect_id=None,
):
    """Insert with owner's transaction and commit before returning protected data.

    Fields are references only. Retries of one delivery may pass the same effect
    UUID; use the caller's business idempotency guard to avoid duplicate inserts.
    A receipt attests an authorized response, not successful network reception.
    """
    if kind not in {"contacts", "resume_pdf", "ats_export", "external_delivery"}:
        raise ValueError("Unsupported disclosure")
    refs = {
        "resource_id": UUID(str(resource_id)),
        "actor_id": UUID(str(actor_id)),
        "candidate_id": UUID(str(candidate_id)),
    }
    if organization_id:
        refs["organization_id"] = UUID(str(organization_id))
    if recipient_id:
        refs["recipient_id"] = UUID(str(recipient_id))
    event = EventEnvelope(
        event_id=effect_id or uuid4(),
        producer=request.app.state.settings.service_name,
        event_type=request.app.state.settings.service_name + "." + kind + "_disclosed.v1",
        correlation_id=request.state.trace_id,
        aggregate_id=UUID(str(resource_id)),
        aggregate_version=1,
        payload=refs,
    )
    enqueue(session, event)
    return event.event_id


class AuditAccess:
    """Configured sender reuses fixed-origin transport; caller can inject `_send`."""

    def __init__(self, settings, signatures, sender):
        self.settings, self.signatures, self._send = settings, signatures, sender

    def record(self, body: DisclosureRequest):
        if body.owner != self.settings.service_name:
            raise ValueError("Disclosure owner mismatch")
        raw, signature = self._send(
            "audit/disclosures",
            canonical(body),
            sign(self.signatures, REQUEST_CONTEXT, body),
            origin=self.settings.audit_api_url,
        )
        from reverse_hr.processing_access import verify

        try:
            receipt = DisclosureReceipt.model_validate_json(raw)
            verify(self.signatures, "audit", signature, RESPONSE_CONTEXT, receipt)
            if receipt.model_dump(include=set(DisclosureRequest.model_fields)) != body.model_dump():
                raise ValueError()
            return receipt
        except Exception as exc:
            raise HTTPException(503, "Invalid Audit receipt") from exc
