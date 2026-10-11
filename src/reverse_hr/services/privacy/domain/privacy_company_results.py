"""Candidate-issued, recipient- and assignment-scoped result permission."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.market_contracts import MarketReceipt, MarketRequest
from reverse_hr.protocols.market_access import Signature, respond
from reverse_hr.services.privacy.domain.privacy import (
    POLICIES,
    ConsentRecord,
    PrivacyBase,
    ProcessingNonce,
    processing_restricted,
    subject_lock,
    utc,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute


class CompanyResultGrant(PrivacyBase):
    __tablename__ = "company_result_grants"
    grant_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    assignment_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36))
    consent_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GrantCommand(Contract):
    assignment_id: UUID
    organization_id: UUID
    consent_id: UUID
    expires_in_days: int = Field(default=30, strict=True, ge=1, le=90)


class GrantView(Contract):
    grant_id: UUID
    assignment_id: UUID
    organization_id: UUID
    consent_id: UUID
    status: Literal["active", "revoked", "expired"]
    version: int
    expires_at: datetime


def consent_allowed(session, row):
    consent = session.get(ConsentRecord, row.consent_id)
    return bool(
        consent
        and consent.candidate_id == row.candidate_id
        and consent.purpose == "company_result_disclosure"
        and consent.status == "active"
        and consent.document_version == POLICIES["company_result_disclosure"]
    )


def view(session, row):
    status = row.status
    if status == "active":
        status = (
            "revoked"
            if not consent_allowed(session, row)
            else ("expired" if utc(row.expires_at) <= datetime.now(UTC) else "active")
        )
    return GrantView(
        grant_id=row.grant_id,
        assignment_id=row.assignment_id,
        organization_id=row.organization_id,
        consent_id=row.consent_id,
        status=status,
        version=row.version,
        expires_at=utc(row.expires_at),
    ).model_dump(mode="json")


router = APIRouter(tags=["company-result-permission"])


@router.post("/v1/company-result-grants", response_model=GrantView, status_code=201)
def create_grant(request: Request, actor: Actor, body: GrantCommand, idempotency: CommandKey):
    actor.require("candidate")

    def change(session):
        row = CompanyResultGrant(
            grant_id=str(uuid4()),
            candidate_id=str(actor.subject),
            assignment_id=str(body.assignment_id),
            organization_id=str(body.organization_id),
            consent_id=str(body.consent_id),
            status="active",
            version=1,
            expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days),
        )
        if not consent_allowed(session, row):
            raise HTTPException(409)
        session.add(row)
        return {"grant_id": row.grant_id}

    def present(session, result):
        row = session.get(CompanyResultGrant, result["grant_id"])
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        return view(session, row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "company_result_grant",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
        present=present,
    )


@router.get("/v1/company-result-grants/{grant_id}", response_model=GrantView)
def get_grant(request: Request, actor: Actor, grant_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(CompanyResultGrant, str(grant_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        return view(session, row)


@router.post("/v1/company-result-grants/{grant_id}/revoke", response_model=GrantView)
def revoke_grant(
    request: Request,
    actor: Actor,
    grant_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def change(session):
        row = session.scalar(
            select(CompanyResultGrant)
            .where(CompanyResultGrant.grant_id == str(grant_id))
            .with_for_update()
        )
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        if row.version != expected or row.status != "active":
            raise HTTPException(409)
        row.status, row.version = "revoked", expected + 1
        return {"grant_id": row.grant_id}

    def present(session, result):
        row = session.get(CompanyResultGrant, result["grant_id"])
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        return view(session, row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"company_result_revoke:{grant_id}",
        idempotency,
        {"version": expected},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
        present=present,
    )


@router.post("/internal/v1/market/company-result-permission", response_model=MarketReceipt)
def permission(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        state = subject_lock(session, body.candidate_id, allow_blocked=True)
        row = session.get(CompanyResultGrant, str(body.result_grant_id))
        allowed = bool(
            not state.blocked
            and not processing_restricted(
                session,
                body.candidate_id,
                domain=body.requester,
                purpose="company_result_disclosure",
            )
            and row
            and row.candidate_id == str(body.candidate_id)
            and row.assignment_id == str(body.assignment_id)
            and row.organization_id == str(body.organization_id)
            and row.status == "active"
            and utc(row.expires_at) > datetime.now(UTC)
            and consent_allowed(session, row)
        )
        return ({"result_grant_id": row.grant_id} if allowed else None), row.version if row else 0

    return respond(
        request,
        body,
        signature,
        "privacy",
        "company-result-permission",
        ProcessingNonce,
        {"assessment"},
        check,
    )
