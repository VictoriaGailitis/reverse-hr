"""Independent employer checks, bounded sanctions and human appeals."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.domains.employer import (
    EmployerBase,
    Membership,
    Organization,
    require_member,
    subject_lock,
    subject_visible,
)


class TrustDecision(EmployerBase):
    __tablename__ = "employer_trust_decisions"
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    dimension: Mapped[str] = mapped_column(String(30))
    status: Mapped[str] = mapped_column(String(16))
    source: Mapped[str] = mapped_column(String(30))
    reason: Mapped[str] = mapped_column(String(2000))
    facts: Mapped[dict] = mapped_column(JSON)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    version: Mapped[int]


class Sanction(EmployerBase):
    __tablename__ = "employer_sanctions"
    sanction_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    reason: Mapped[str] = mapped_column(String(2000))
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]


class TrustAppeal(EmployerBase):
    __tablename__ = "employer_trust_appeals"
    appeal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    target_id: Mapped[str] = mapped_column(String(36), unique=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]


class LegalFacts(Contract):
    legal_name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    tax_id: str = Field(pattern=r"^(?:[0-9]{10}|[0-9]{12})$")
    registry_reference: str = Field(min_length=1, max_length=300, pattern=r"\S")


class RepresentativeFacts(Contract):
    representative_subject: UUID
    corporate_domain: str = Field(
        max_length=253, pattern=r"^[a-z0-9]+(?:[.-][a-z0-9]+)*\.[a-z]{2,63}$"
    )
    evidence_reference: str = Field(min_length=1, max_length=300, pattern=r"\S")


class TrustCommand(Contract):
    dimension: Literal["legal", "representative"]
    status: Literal["verified", "rejected"]
    source: Literal["manual_review", "demo_registry"] = "manual_review"
    facts: LegalFacts | RepresentativeFacts
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")

    @model_validator(mode="after")
    def dimension_facts(self):
        if (self.dimension == "legal") != isinstance(self.facts, LegalFacts):
            raise ValueError("Facts must match verification dimension")
        return self


class SanctionCommand(Contract):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    duration_days: int = Field(ge=1, le=365, strict=True)


class AppealCommand(Contract):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class AppealDecision(AppealCommand):
    outcome: Literal["upheld", "overturned"]


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def independent(session, request, actor, org, excluded=()):
    actor.require("company_moderator", mfa=True)
    subject_lock(session, actor.subject)
    request.app.state.processing_access.check(actor.subject)
    if (
        str(actor.subject) in set(excluded)
        or session.scalar(
            select(Membership).where(
                Membership.organization_id == str(org), Membership.subject == str(actor.subject)
            )
        )
        is not None
    ):
        raise HTTPException(403)


def org_lock(session, org):
    row = session.scalar(
        select(Organization)
        .where(Organization.organization_id == str(org))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404)
    return row


def permitted(session, request, org):
    """Live authorization: expiry restores access without deleting audit history."""
    now = datetime.now(UTC)
    sanctions = session.scalars(
        select(Sanction).where(
            Sanction.organization_id == org.organization_id, Sanction.status == "active"
        )
    )
    if any(utc(row.starts_at) <= now < utc(row.ends_at) for row in sanctions):
        return False
    decisions = list(
        session.scalars(
            select(TrustDecision)
            .where(TrustDecision.organization_id == org.organization_id)
            .order_by(TrustDecision.version.desc())
        )
    )
    if not decisions:
        return not org.trust_required  # Never fall back after new check evidence is erased.
    latest = {}
    for row in decisions:
        latest.setdefault(row.dimension, row)
    return set(latest) == {"legal", "representative"} and all(
        row.status == "verified" and subject_visible(session, request, row.reviewer_id)
        for row in latest.values()
    )


def snapshot(session, org_id):
    checks = list(
        session.scalars(
            select(TrustDecision)
            .where(TrustDecision.organization_id == str(org_id))
            .order_by(TrustDecision.version)
        )
    )
    sanctions = list(
        session.scalars(
            select(Sanction)
            .where(Sanction.organization_id == str(org_id))
            .order_by(Sanction.starts_at)
        )
    )
    return {
        "organization_id": str(org_id),
        "checks": [
            {
                "decision_id": row.decision_id,
                "dimension": row.dimension,
                "status": row.status,
                "source": row.source,
                "reason": row.reason,
                "facts": row.facts,
                "reviewer_id": row.reviewer_id,
                "decided_at": utc(row.decided_at).isoformat(),
                "version": row.version,
            }
            for row in checks
        ],
        "sanctions": [
            {
                "sanction_id": row.sanction_id,
                "reason": row.reason,
                "status": "expired"
                if row.status == "active" and utc(row.ends_at) <= datetime.now(UTC)
                else row.status,
                "starts_at": utc(row.starts_at).isoformat(),
                "ends_at": utc(row.ends_at).isoformat(),
                "version": row.version,
            }
            for row in sanctions
        ],
    }


router = APIRouter(prefix="/v1/organizations", tags=["employer-trust"])


@router.get("/{organization_id}/trust")
def history(request: Request, actor: Actor, organization_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        if "company_moderator" in actor.roles:
            independent(session, request, actor, organization_id)
        else:
            require_member(session, organization_id, actor, owner=True)
            request.app.state.processing_access.check(actor.subject)
        org_lock(session, organization_id)
        result = snapshot(session, organization_id)
        result["checks"] = [
            row for row in result["checks"] if subject_visible(session, request, row["reviewer_id"])
        ]
        return result


@router.post("/{organization_id}/trust-checks")
def check(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    body: TrustCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        subjects = {str(actor.subject)}
        if isinstance(body.facts, RepresentativeFacts):
            subjects.add(str(body.facts.representative_subject))
        for subject in sorted(subjects):
            subject_lock(session, subject)
            request.app.state.processing_access.check(UUID(subject))
        independent(session, request, actor, organization_id)
        org_lock(session, organization_id)

    def change(session):
        org = org_lock(session, organization_id)
        if org.version != int(if_match.strip('"')):
            raise HTTPException(409)
        if body.source == "demo_registry" and request.app.state.settings.deployment_mode != "demo":
            raise HTTPException(409)
        if isinstance(body.facts, RepresentativeFacts):
            member = session.scalar(
                select(Membership).where(
                    Membership.organization_id == str(organization_id),
                    Membership.subject == str(body.facts.representative_subject),
                    Membership.status == "active",
                )
            )
            if member is None:
                raise HTTPException(409)
            subject_lock(session, member.subject)
            request.app.state.processing_access.check(UUID(member.subject))
        org.trust_required = True
        org.version += 1
        row = TrustDecision(
            decision_id=str(uuid4()),
            organization_id=str(organization_id),
            reviewer_id=str(actor.subject),
            **body.model_dump(mode="json"),
            decided_at=datetime.now(UTC),
            version=org.version,
        )
        session.add(row)
        session.flush()
        if permitted(session, request, org):
            org.verification_status, org.verified_by, org.verification_reason = (
                "verified",
                str(actor.subject),
                "Independent legal and representative checks",
            )
        else:
            org.verification_status = "rejected" if body.status == "rejected" else "pending"
        return {"decision_id": row.decision_id, "version": org.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"trust_check:{organization_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=guard,
    )


@router.post("/{organization_id}/sanctions", status_code=201)
def impose(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    body: SanctionCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        independent(session, request, actor, organization_id)
        org_lock(session, organization_id)

    def change(session):
        org = org_lock(session, organization_id)
        if org.version != int(if_match.strip('"')):
            raise HTTPException(409)
        now = datetime.now(UTC)
        row = Sanction(
            sanction_id=str(uuid4()),
            organization_id=str(organization_id),
            reviewer_id=str(actor.subject),
            reason=body.reason,
            starts_at=now,
            ends_at=now + timedelta(days=body.duration_days),
            status="active",
            version=1,
        )
        org.version += 1
        session.add(row)
        return {"sanction_id": row.sanction_id, "version": 1, "organization_version": org.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"sanction:{organization_id}",
        idempotency,
        body.model_dump() | {"version": if_match},
        change,
        201,
        guard=guard,
    )


@router.post("/{organization_id}/trust-appeals/{target_id}", status_code=201)
def appeal(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    target_id: UUID,
    body: AppealCommand,
    idempotency: CommandKey,
):
    def guard(session):
        require_member(session, organization_id, actor, owner=True)
        request.app.state.processing_access.check(actor.subject)
        org_lock(session, organization_id)

    def change(session):
        target = session.get(Sanction, str(target_id)) or session.get(TrustDecision, str(target_id))
        if target is None or target.organization_id != str(organization_id):
            raise HTTPException(404)
        if isinstance(target, TrustDecision) and target.status != "rejected":
            raise HTTPException(409)
        row = TrustAppeal(
            appeal_id=str(uuid4()),
            organization_id=str(organization_id),
            target_id=str(target_id),
            author_id=str(actor.subject),
            status="open",
            version=1,
            data={
                "reason": body.reason,
                "created_at": datetime.now(UTC).isoformat(),
                "due_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
            },
        )
        session.add(row)
        session.flush()
        return {"appeal_id": row.appeal_id, "status": row.status, "version": row.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"trust_appeal:{target_id}",
        idempotency,
        body.model_dump(),
        change,
        201,
        guard=guard,
    )


@router.get("/{organization_id}/trust-appeals")
def appeals(request: Request, actor: Actor, organization_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        if "company_moderator" in actor.roles:
            independent(session, request, actor, organization_id)
        else:
            require_member(session, organization_id, actor, owner=True)
        request.app.state.processing_access.check(actor.subject)
        return [
            {
                "appeal_id": row.appeal_id,
                "target_id": row.target_id,
                "status": row.status,
                "version": row.version,
                **row.data,
            }
            for row in session.scalars(
                select(TrustAppeal)
                .where(TrustAppeal.organization_id == str(organization_id))
                .order_by(TrustAppeal.appeal_id)
                .limit(50)
            )
            if subject_visible(session, request, row.author_id)
        ]


@router.post("/{organization_id}/trust-appeals/{appeal_id}/decision")
def resolve(
    request: Request,
    actor: Actor,
    organization_id: UUID,
    appeal_id: UUID,
    body: AppealDecision,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        from reverse_hr.review_sla import assignment_guard

        assignment_guard(session, "employer", "trust_appeal", appeal_id, actor)
        row = session.get(TrustAppeal, str(appeal_id))
        if row is None or row.organization_id != str(organization_id):
            raise HTTPException(404)
        target = session.get(Sanction, row.target_id) or session.get(TrustDecision, row.target_id)
        if target is None:
            raise HTTPException(404)
        for subject in sorted({str(actor.subject), row.author_id, target.reviewer_id}):
            subject_lock(session, subject)
            request.app.state.processing_access.check(UUID(subject))
        independent(session, request, actor, organization_id, (row.author_id, target.reviewer_id))
        org_lock(session, organization_id)

    def change(session):
        row = session.scalar(
            select(TrustAppeal)
            .where(TrustAppeal.appeal_id == str(appeal_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row.status != "open" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        target = session.get(Sanction, row.target_id) or session.get(TrustDecision, row.target_id)
        org = org_lock(session, organization_id)
        if body.outcome == "overturned":
            if isinstance(target, Sanction):
                target.status, target.version = "revoked", target.version + 1
            else:
                latest = session.scalar(
                    select(TrustDecision)
                    .where(
                        TrustDecision.organization_id == str(organization_id),
                        TrustDecision.dimension == target.dimension,
                    )
                    .order_by(TrustDecision.version.desc())
                    .limit(1)
                )
                if latest.decision_id != target.decision_id:
                    raise HTTPException(409)
                session.add(
                    TrustDecision(
                        decision_id=str(uuid4()),
                        organization_id=str(organization_id),
                        reviewer_id=str(actor.subject),
                        dimension=target.dimension,
                        status="verified",
                        source="manual_review",
                        reason=body.reason,
                        facts=target.facts,
                        decided_at=datetime.now(UTC),
                        version=org.version + 1,
                    )
                )
        org.version += 1
        row.status, row.version, row.reviewer_id = body.outcome, row.version + 1, str(actor.subject)
        row.data = row.data | {
            "decision_reason": body.reason,
            "decided_at": datetime.now(UTC).isoformat(),
        }
        session.flush()
        if permitted(session, request, org):
            org.verification_status, org.verified_by = "verified", str(actor.subject)
        return {"appeal_id": row.appeal_id, "status": row.status, "version": row.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"trust_appeal_decision:{appeal_id}",
        idempotency,
        body.model_dump() | {"version": if_match},
        change,
        guard=guard,
    )


def scrub(session, subject):
    from reverse_hr.review_sla import scrub as scrub_sla

    scrub_sla(session, "employer", subject)
    # Employer retention contract remains authoritative; remove new free-text PD.
    removed_ids = []
    for row in session.scalars(select(TrustDecision)):
        if row.reviewer_id == subject or row.facts.get("representative_subject") == subject:
            org = session.get(Organization, row.organization_id)
            if org is not None:
                org.trust_required, org.verification_status = True, "pending"
                org.version += 1
            removed_ids.append(row.decision_id)
            session.delete(row)
    session.flush()
    ids = list(
        session.scalars(
            select(TrustDecision.decision_id).where(TrustDecision.reviewer_id == subject)
        )
    )
    ids += removed_ids
    ids += list(
        session.scalars(select(Sanction.sanction_id).where(Sanction.reviewer_id == subject))
    )
    session.execute(
        delete(TrustAppeal).where(
            (TrustAppeal.author_id == subject)
            | (TrustAppeal.reviewer_id == subject)
            | TrustAppeal.target_id.in_(ids)
        )
    )
    session.execute(delete(TrustDecision).where(TrustDecision.reviewer_id == subject))
    # Keep restriction duration, erase reviewer identity/reason to prevent restoration by erasure.
    for row in session.scalars(select(Sanction).where(Sanction.reviewer_id == subject)):
        row.reviewer_id, row.reason = str(UUID(int=0)), "Reviewer data erased"


@router.get("/trust-appeals/queue")
def appeal_queue(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("company_moderator", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(TrustAppeal).where(TrustAppeal.status == "open")
        if after:
            query = query.where(TrustAppeal.appeal_id > str(after))
        result = []
        for row in session.scalars(query.order_by(TrustAppeal.appeal_id).limit(50)):
            target = session.get(Sanction, row.target_id) or session.get(
                TrustDecision, row.target_id
            )
            if target is None:
                continue
            try:
                independent(
                    session,
                    request,
                    actor,
                    row.organization_id,
                    (row.author_id, target.reviewer_id),
                )
                if not subject_visible(session, request, row.author_id):
                    continue
            except HTTPException as exc:
                if exc.status_code in {403, 409}:
                    continue
                raise
            result.append(
                {
                    "appeal_id": row.appeal_id,
                    "organization_id": row.organization_id,
                    "due_at": row.data["due_at"],
                    "version": row.version,
                }
            )
        return result
