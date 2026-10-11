"""Fresh publication consent and exact-invitation disclosure permission."""

from datetime import UTC, datetime

from fastapi import APIRouter, Request
from sqlalchemy import select

from reverse_hr.contracts.market_contracts import MarketReceipt, MarketRequest
from reverse_hr.protocols.market_access import Signature, respond
from reverse_hr.services.privacy.domain.privacy import (
    EXTERNAL_NOTIFICATION_PURPOSES,
    POLICIES,
    ConsentRecord,
    ContactGrant,
    ProcessingNonce,
    processing_restricted,
    subject_lock,
)

router = APIRouter(prefix="/internal/v1/market", tags=["internal-recruitment-permission"])


@router.post("/purpose-permission", response_model=MarketReceipt)
def purpose_permission(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        subject = subject_lock(session, body.candidate_id, allow_blocked=True)
        consent = session.get(ConsentRecord, str(body.consent_id))
        allowed = bool(
            (subject is None or not subject.blocked)
            and not processing_restricted(
                session, body.candidate_id, domain=body.requester, purpose=body.consent_purpose
            )
            and consent
            and consent.candidate_id == str(body.candidate_id)
            and consent.purpose == body.consent_purpose
            and consent.status == "active"
            and consent.document_version == POLICIES[body.consent_purpose]
        )
        return (dict(consent_id=str(body.consent_id)) if allowed else None), 0

    return respond(
        request,
        body,
        signature,
        "privacy",
        "purpose-permission",
        ProcessingNonce,
        {"candidate", "hiring", "assessment", "achievements", "integration"}
        | ({"notification"} if body.consent_purpose in EXTERNAL_NOTIFICATION_PURPOSES else set()),
        check,
    )


@router.post("/contact-permission", response_model=MarketReceipt)
def contact_permission(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        subject = subject_lock(session, body.candidate_id, allow_blocked=True)
        if (subject and subject.blocked) or processing_restricted(
            session, body.candidate_id, domain=body.requester, purpose="contact_disclosure"
        ):
            return None, 0
        row = session.scalar(
            select(ContactGrant)
            .join(ConsentRecord, ConsentRecord.consent_id == ContactGrant.consent_id)
            .where(
                ContactGrant.candidate_id == str(body.candidate_id),
                ContactGrant.organization_id == str(body.organization_id),
                ContactGrant.invitation_id == str(body.invitation_id),
                ContactGrant.status == "active",
                ContactGrant.expires_at > datetime.now(UTC),
                ConsentRecord.candidate_id == str(body.candidate_id),
                ConsentRecord.status == "active",
                ConsentRecord.purpose == "contact_disclosure",
                ConsentRecord.document_version == POLICIES["contact_disclosure"],
            )
        )
        return (dict(grant_id=row.grant_id) if row else None), 0

    return respond(
        request,
        body,
        signature,
        "privacy",
        "contact-permission",
        ProcessingNonce,
        {"candidate", "hiring", "integration"},
        check,
    )
