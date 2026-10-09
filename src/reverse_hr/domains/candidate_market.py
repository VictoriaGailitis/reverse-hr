"""Consent-gated search cards and separately authorized contact disclosure."""

from datetime import UTC
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.confirmed_grade_access import DecisionSummary
from reverse_hr.contracts import Grade
from reverse_hr.domains.candidate import CandidateBase, CandidateProfile, router, subject_lock
from reverse_hr.domains.candidate_grades import active_decisions, current_grade
from reverse_hr.market_access import Signature, respond
from reverse_hr.market_contracts import (
    CandidateCard,
    ContactsCommand,
    MarketReceipt,
    MarketRequest,
    PublicationCommand,
)
from reverse_hr.market_state import NonceColumns


class Publication(CandidateBase):
    __tablename__ = "candidate_publication"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    published: Mapped[bool]
    consent_id: Mapped[str | None] = mapped_column(String(36))
    declared_skills: Mapped[list] = mapped_column(JSON)


class Contacts(CandidateBase):
    __tablename__ = "candidate_contacts"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    phone: Mapped[str | None] = mapped_column(String(30))
    version: Mapped[int] = mapped_column(default=1, server_default="1")


class CandidateNonce(NonceColumns, CandidateBase):
    __tablename__ = "candidate_market_nonces"


internal_router = APIRouter(prefix="/internal/v1/market", tags=["internal-candidate-market"])


def emit_profile(session, row, correlation):
    from reverse_hr.db import enqueue
    from reverse_hr.events import EventEnvelope

    enqueue(
        session,
        EventEnvelope(
            producer="candidate",
            event_type="candidate.profile_updated.v1",
            aggregate_id=UUID(row.candidate_id),
            aggregate_version=row.version,
            correlation_id=correlation,
            payload={"candidate_id": UUID(row.candidate_id)},
        ),
    )


@router.put("/me/publication", response_model=PublicationCommand)
def publish(
    request: Request,
    actor: Actor,
    body: PublicationCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")

    def guard(session):
        subject_lock(session, actor.subject)
        if body.published:
            request.app.state.market_access.require(
                "privacy",
                "purpose-permission",
                candidate_id=actor.subject,
                consent_id=body.consent_id,
                consent_purpose="profile_publication",
            )

    def change(session):
        row = session.get(CandidateProfile, str(actor.subject))
        if row is None:
            raise HTTPException(404)
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        listing = session.get(Publication, row.candidate_id)
        if listing is None:
            listing = Publication(candidate_id=row.candidate_id)
            session.add(listing)
        listing.published, listing.consent_id, listing.declared_skills = (
            body.published,
            str(body.consent_id) if body.consent_id else None,
            body.declared_skills,
        )
        row.version += 1
        emit_profile(session, row, request.state.trace_id)
        return body.model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        "publication",
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        guard=guard,
    )


@router.put("/me/contacts", response_model=ContactsCommand)
def update_contacts(request: Request, actor: Actor, body: ContactsCommand, idempotency: CommandKey):
    actor.require("candidate")

    def change(session):
        row = session.get(Contacts, str(actor.subject))
        if row is None:
            row = Contacts(candidate_id=str(actor.subject))
            session.add(row)
            row.version = 1
        else:
            row.version += 1
        row.email, row.phone = body.email, body.phone
        return body.model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        "contacts",
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@internal_router.post("/profile", response_model=MarketReceipt)
def profile_card(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        state = subject_lock(session, body.candidate_id, allow_blocked=True)
        row = session.get(CandidateProfile, str(body.candidate_id))
        listing = session.get(Publication, str(body.candidate_id))
        revision = row.version if row else 0
        if state.blocked or row is None or listing is None or not listing.published:
            return None, revision
        try:
            request.app.state.processing_access.check(body.candidate_id)
            request.app.state.market_access.require(
                "privacy",
                "purpose-permission",
                candidate_id=body.candidate_id,
                consent_id=UUID(listing.consent_id),
                consent_purpose="profile_publication",
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            return None, revision
        grade = current_grade(session, body.candidate_id, row.specialization)
        evidence = [
            d
            for d in active_decisions(session, row.candidate_id)
            if d.summary["specialization"] == row.specialization
            and d.summary["status"] == "confirmed"
            and Grade(d.summary["target_grade"]) == grade
        ]
        # Keep the first observed confirmation stable when another same-grade decision arrives.
        evidence.sort(
            key=lambda d: (
                d.received_at.replace(tzinfo=UTC)
                if d.received_at.tzinfo is None
                else d.received_at.astimezone(UTC),
                d.decision_id,
            )
        )
        # Refresh reviewed evidence on same-grade retests, without changing the grade.
        from reverse_hr.domains.candidate_grades import grade_binding

        _, decision = grade_binding(session, body.candidate_id, row.specialization)
        chosen = next((item for item in evidence if item.decision_id == decision), None)
        from reverse_hr.domains.candidate_preferences import public_preferences

        card = CandidateCard(
            preferences=public_preferences(session, body.candidate_id),
            candidate_id=body.candidate_id,
            display_name=row.display_name,
            specialization=row.specialization,
            confirmed_grade=grade,
            decision_id=decision,
            version=row.version,
            declared_skills=listing.declared_skills,
            qualification=DecisionSummary.model_validate(chosen.summary).qualification
            if chosen
            else None,
        ).model_dump(mode="json")
        try:
            request.app.state.processing_access.check(body.candidate_id)
            request.app.state.market_access.require(
                "privacy",
                "purpose-permission",
                candidate_id=body.candidate_id,
                consent_id=UUID(listing.consent_id),
                consent_purpose="profile_publication",
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            return None, revision
        return card, revision

    return respond(
        request,
        body,
        signature,
        "candidate",
        "profile",
        CandidateNonce,
        {"matching", "hiring", "integration"},
        check,
    )


@internal_router.post("/contacts", response_model=MarketReceipt)
def disclose(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        state = subject_lock(session, body.candidate_id, allow_blocked=True)
        row = session.get(Contacts, str(body.candidate_id))
        if state.blocked or row is None:
            return None, 0
        try:
            request.app.state.processing_access.check(body.candidate_id)
            request.app.state.market_access.require(
                "employer",
                "membership",
                candidate_id=body.actor_id,
                actor_id=body.actor_id,
                organization_id=body.organization_id,
            )
            grant = request.app.state.market_access.require(
                "privacy",
                "contact-permission",
                candidate_id=body.candidate_id,
                organization_id=body.organization_id,
                invitation_id=body.invitation_id,
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            return None, 0
        from reverse_hr.audit_access import record_disclosure

        record_disclosure(
            session,
            request,
            "contacts",
            body.invitation_id,
            body.actor_id,
            body.candidate_id,
            body.organization_id,
        )
        return dict(
            candidate_id=str(body.candidate_id),
            organization_id=str(body.organization_id),
            grant_id=grant.data["grant_id"],
            email=row.email,
            phone=row.phone,
        ), 0

    return respond(
        request,
        body,
        signature,
        "candidate",
        "contacts",
        CandidateNonce,
        {"hiring", "integration"},
        check,
    )
