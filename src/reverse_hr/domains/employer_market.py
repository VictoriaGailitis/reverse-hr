"""Membership authorization belongs to Employer, never to a copied JWT."""

from fastapi import APIRouter, Request
from sqlalchemy import select

from reverse_hr.domains.employer import (
    EmployerBase,
    Membership,
    Organization,
    subject_lock,
    subject_visible,
)
from reverse_hr.domains.employer_trust import permitted
from reverse_hr.market_access import Signature, respond
from reverse_hr.market_contracts import MarketReceipt, MarketRequest
from reverse_hr.market_state import NonceColumns


class EmployerNonce(NonceColumns, EmployerBase):
    __tablename__ = "employer_market_nonces"


router = APIRouter(prefix="/internal/v1/market", tags=["internal-employer-authorization"])


@router.post("/membership", response_model=MarketReceipt)
def membership(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        state = subject_lock(session, body.actor_id, allow_blocked=True)
        row = session.scalar(
            select(Membership).where(
                Membership.subject == str(body.actor_id),
                Membership.organization_id == str(body.organization_id),
                Membership.status == "active",
                Membership.role.in_(["owner", "recruiter"]),
            )
        )
        org = session.get(Organization, str(body.organization_id))
        if (
            state.blocked
            or row is None
            or org is None
            or org.verification_status != "verified"
            or not permitted(session, request, org)
            or not org.verified_by
            or not subject_visible(session, request, body.actor_id)
            or not subject_visible(session, request, org.verified_by)
        ):
            return None, org.version if org else 0
        return dict(organization_id=org.organization_id, role=row.role), org.version

    return respond(
        request,
        body,
        signature,
        "employer",
        "membership",
        EmployerNonce,
        {"matching", "hiring", "candidate", "integration", "demo-ats"},
        check,
    )


@router.post("/affiliation", response_model=MarketReceipt)
def affiliation(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        state = subject_lock(session, body.actor_id, allow_blocked=True)
        if state.blocked or not subject_visible(session, request, body.actor_id):
            return None, 0
        row = session.scalar(
            select(Membership).where(
                Membership.organization_id == str(body.organization_id),
                Membership.subject == str(body.actor_id),
                Membership.status == "active",
            )
        )
        if row is None:
            return None, 0
        return dict(organization_id=row.organization_id, role=row.role), row.version

    return respond(
        request,
        body,
        signature,
        "employer",
        "affiliation",
        EmployerNonce,
        {"hiring", "assessment", "evaluation"},
        check,
    )


@router.post("/content-membership", response_model=MarketReceipt)
def content_membership(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        state = subject_lock(session, body.actor_id, allow_blocked=True)
        row = session.scalar(
            select(Membership).where(
                Membership.organization_id == str(body.organization_id),
                Membership.subject == str(body.actor_id),
                Membership.status == "active",
            )
        )
        org = session.get(Organization, str(body.organization_id))
        if (
            state.blocked
            or row is None
            or org is None
            or org.verification_status != "verified"
            or not permitted(session, request, org)
            or not org.verified_by
            or not subject_visible(session, request, body.actor_id)
            or not subject_visible(session, request, org.verified_by)
        ):
            return None, 0
        return dict(organization_id=row.organization_id, role=row.role), row.version

    return respond(
        request,
        body,
        signature,
        "employer",
        "content-membership",
        EmployerNonce,
        {"assessment"},
        check,
    )
