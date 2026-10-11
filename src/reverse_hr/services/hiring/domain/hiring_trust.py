"""Interaction-backed structured reviews and independent moderation appeals.

Public reviews intentionally contain only controlled tags and scores, never free text,
contact details, names, candidate identifiers or invitation identifiers.
"""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, String, UniqueConstraint, cast, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.protocols.market_state import lock
from reverse_hr.services.hiring.domain.hiring import (
    HiringBase,
    HiringSubject,
    InvitationRow,
    invitation_guard,
    router,
)
from reverse_hr.services.hiring.domain.hiring_moderation import (
    ComplaintDecision,
    guard_case,
    related,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute


class EmployerReview(HiringBase):
    __tablename__ = "hiring_employer_reviews"
    __table_args__ = (UniqueConstraint("invitation_id"),)
    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invitation_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int]


class ModerationAppeal(HiringBase):
    __tablename__ = "hiring_moderation_appeals"
    appeal_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    target_id: Mapped[str] = mapped_column(String(36), index=True)
    target_version: Mapped[int]
    kind: Mapped[str] = mapped_column(String(16))
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str | None] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16))
    data: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int]
    __table_args__ = (UniqueConstraint("target_id", "target_version", "author_id"),)


class ReviewCommand(Contract):
    score: int = Field(ge=1, le=5, strict=True)
    experience: Literal["communication", "interview", "offer"]
    tag: Literal["clear_process", "respectful", "slow_response", "unclear_terms"]


class ReplyCommand(Contract):
    response: Literal["acknowledged", "process_improved", "disagree"]


class ReviewDecision(Contract):
    outcome: Literal["published", "rejected"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class AppealCommand(Contract):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class AppealDecision(AppealCommand):
    outcome: Literal["upheld", "overturned"]


def view(row):
    return {
        "review_id": row.review_id,
        "organization_id": row.organization_id,
        "score": row.data["score"],
        "experience": row.data["experience"],
        "tag": row.data["tag"],
        "response": row.data.get("response"),
        "version": row.version,
    }


def review_guard(request, actor, session, review_id, moderator=False, excluded=()):
    row = session.get(EmployerReview, str(review_id))
    if moderator and row is not None and row.status == "pending":
        from reverse_hr.coordination.review_sla import assignment_guard

        assignment_guard(session, "hiring", "employer_review", review_id, actor)
    if row is None:
        raise HTTPException(404)
    invitation = session.get(InvitationRow, row.invitation_id)
    if invitation is None:
        raise HTTPException(404)
    subjects = {str(actor.subject), row.author_id, invitation.created_by} | (
        {row.reviewer_id} if row.reviewer_id else set()
    )
    for subject in sorted(subjects):
        lock(session, HiringSubject, subject)
        request.app.state.processing_access.check(UUID(subject))
    if moderator:
        actor.require("company_moderator", mfa=True)
        if str(actor.subject) in {row.author_id, invitation.created_by, *excluded}:
            raise HTTPException(403)
        affiliation = request.app.state.market_access.fetch(
            "employer",
            "affiliation",
            candidate_id=actor.subject,
            actor_id=actor.subject,
            organization_id=UUID(row.organization_id),
        )
        if affiliation.allowed:
            raise HTTPException(403)
    else:
        invitation_guard(request, actor, UUID(row.invitation_id), session)
    return session.scalar(
        select(EmployerReview)
        .where(EmployerReview.review_id == str(review_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )


@router.post("/invitations/{invitation_id}/reviews", status_code=201)
def create_review(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    body: ReviewCommand,
    idempotency: CommandKey,
):
    verified_stage = body.experience == "communication"
    if not verified_stage:
        from reverse_hr.services.hiring.domain.hiring_ats import ATSProjection, outcome

        # Resolve current external evidence before local actor locks; the signed
        # Integration permission path calls back into Hiring.
        with Session(request.app.state.engine) as session:
            invitation = session.get(InvitationRow, str(invitation_id))
            if invitation is None or invitation.candidate_id != str(actor.subject):
                raise HTTPException(404)
            jobs = list(
                session.scalars(
                    select(ATSProjection.job_id).where(
                        ATSProjection.invitation_id == str(invitation_id)
                    )
                )
            )
            org_id = invitation.organization_id
        request.app.state.processing_access.check(actor.subject)
        allowed = (
            {"interview", "offer", "hired"}
            if body.experience == "interview"
            else {"offer", "hired"}
        )
        for job_id in jobs:
            data = outcome(request.app.state.exchange_access, actor.subject, job_id)
            if (
                data
                and data["invitation_id"] == str(invitation_id)
                and data["organization_id"] == org_id
                and data["status"] in allowed
            ):
                verified_stage = True
        if not verified_stage:
            raise HTTPException(409)

    def guard(session):
        invitation_guard(request, actor, invitation_id, session, candidate_only=True)

    def change(session):
        invitation = invitation_guard(request, actor, invitation_id, session, candidate_only=True)
        if invitation.status != "accepted":
            raise HTTPException(409)
        row = EmployerReview(
            review_id=str(uuid4()),
            invitation_id=str(invitation_id),
            organization_id=invitation.organization_id,
            author_id=str(actor.subject),
            status="pending",
            version=1,
            data=body.model_dump() | {"created_at": datetime.now(UTC).isoformat()},
        )
        session.add(row)
        session.flush()
        return {"review_id": row.review_id, "status": row.status, "version": row.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"employer_review:{invitation_id}",
        idempotency,
        body.model_dump(),
        change,
        201,
        guard=guard,
    )


@router.get("/organizations/{organization_id}/reviews")
def public_reviews(
    request: Request, actor: Actor, organization_id: UUID, after: UUID | None = None
):
    request.app.state.processing_access.check(actor.subject)
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, HiringSubject, actor.subject)
        query = select(EmployerReview).where(
            EmployerReview.organization_id == str(organization_id),
            EmployerReview.status == "published",
        )
        if after:
            query = query.where(EmployerReview.review_id > str(after))
        rows = list(session.scalars(query.order_by(EmployerReview.review_id).limit(50)))
        subjects = {s for row in rows for s in (row.author_id, row.reviewer_id) if s}
        for subject in sorted(subjects):
            lock(session, HiringSubject, subject, allow_blocked=True)
        result = []
        for row in rows:
            try:
                for subject in (row.author_id, row.reviewer_id):
                    if subject:
                        lock(session, HiringSubject, subject)
                        request.app.state.processing_access.check(UUID(subject))
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                raise
            session.refresh(row)
            if row.status != "published" or (row.reviewer_id and row.reviewer_id not in subjects):
                continue
            result.append(view(row))
        return result


@router.get("/employer-reviews/{review_id}")
def get_review(request: Request, actor: Actor, review_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = review_guard(request, actor, session, review_id, "company_moderator" in actor.roles)
        return view(row) | {
            "status": row.status,
            "moderation_reason": row.data.get("moderation_reason"),
        }


@router.post("/employer-reviews/{review_id}/reply")
def reply(
    request: Request,
    actor: Actor,
    review_id: UUID,
    body: ReplyCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("employer")

    def guard(session):
        row = review_guard(request, actor, session, review_id)
        if row.author_id == str(actor.subject):
            raise HTTPException(403)

    def change(session):
        row = review_guard(request, actor, session, review_id)
        if row.status != "published" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.data, row.version = row.data | body.model_dump(), row.version + 1
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"review_reply:{review_id}",
        idempotency,
        body.model_dump() | {"version": if_match},
        change,
        guard=guard,
    )


@router.post("/employer-reviews/{review_id}/moderation")
def moderate(
    request: Request,
    actor: Actor,
    review_id: UUID,
    body: ReviewDecision,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        review_guard(request, actor, session, review_id, True)

    def change(session):
        row = review_guard(request, actor, session, review_id, True)
        if row.version != int(if_match.strip('"')) or row.status != "pending":
            raise HTTPException(409)
        row.status, row.version, row.reviewer_id = body.outcome, row.version + 1, str(actor.subject)
        row.data = row.data | {
            "moderation_reason": body.reason,
            "moderated_at": datetime.now(UTC).isoformat(),
        }
        return {"review_id": row.review_id, "status": row.status, "version": row.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"review_moderation:{review_id}",
        idempotency,
        body.model_dump() | {"version": if_match},
        change,
        guard=guard,
    )


def appeal_target(request, actor, session, kind, target_id, moderator=False, excluded=()):
    if kind == "review":
        row = review_guard(request, actor, session, target_id, moderator, excluded)
        if row.status not in {"published", "rejected"}:
            raise HTTPException(409)
        return row, row.version, row.reviewer_id
    data = related(session, target_id)
    if moderator:
        guard_case(request, actor, session, target_id)
        if str(actor.subject) in excluded:
            raise HTTPException(403)
    else:
        invitation_guard(request, actor, UUID(data[2].invitation_id), session)
    if data[1].status == "open" or not data[4]:
        raise HTTPException(409)
    return data[1], data[1].version, data[4][-1].reviewer_id


@router.post("/moderation-appeals/targets/{kind}/{target_id}", status_code=201)
def appeal(
    request: Request,
    actor: Actor,
    kind: Literal["review", "complaint"],
    target_id: UUID,
    body: AppealCommand,
    idempotency: CommandKey,
):
    def guard(session):
        appeal_target(request, actor, session, kind, target_id)

    def change(session):
        target, version, reviewer = appeal_target(request, actor, session, kind, target_id)
        if reviewer == str(actor.subject):
            raise HTTPException(403)
        row = ModerationAppeal(
            appeal_id=str(uuid4()),
            target_id=str(target_id),
            target_version=version,
            kind=kind,
            author_id=str(actor.subject),
            status="open",
            version=1,
            data={
                "reason": body.reason,
                "due_at": (datetime.now(UTC) + timedelta(days=14)).isoformat(),
                "original_reviewer": reviewer,
                "original_outcome": target.status,
                "original_reason": target.data.get("moderation_reason")
                if kind == "review"
                else related(session, target_id)[4][-1].reason,
            },
        )
        session.add(row)
        session.flush()
        return {"appeal_id": row.appeal_id, "status": row.status, "version": 1}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"moderation_appeal:{kind}:{target_id}",
        idempotency,
        body.model_dump(),
        change,
        201,
        guard=guard,
    )


def appeal_guard(request, actor, session, appeal_id):
    row = session.get(ModerationAppeal, str(appeal_id))
    if "company_moderator" in actor.roles:
        from reverse_hr.coordination.review_sla import assignment_guard

        assignment_guard(session, "hiring", "moderation_appeal", appeal_id, actor)
    if row is None:
        raise HTTPException(404)
    for subject in sorted({str(actor.subject), row.author_id, row.data["original_reviewer"]}):
        lock(session, HiringSubject, subject)
        request.app.state.processing_access.check(UUID(subject))
    moderator = "company_moderator" in actor.roles
    if not moderator and row.author_id != str(actor.subject):
        raise HTTPException(404)
    appeal_target(
        request,
        actor,
        session,
        row.kind,
        row.target_id,
        moderator,
        (row.author_id, row.data["original_reviewer"]),
    )
    return session.scalar(
        select(ModerationAppeal)
        .where(ModerationAppeal.appeal_id == str(appeal_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )


@router.get("/moderation-appeals/{appeal_id}")
def get_appeal(request: Request, actor: Actor, appeal_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = appeal_guard(request, actor, session, appeal_id)
        return {
            "appeal_id": row.appeal_id,
            "status": row.status,
            "version": row.version,
            **row.data,
        }


@router.post("/moderation-appeals/{appeal_id}/decision")
def resolve(
    request: Request,
    actor: Actor,
    appeal_id: UUID,
    body: AppealDecision,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("company_moderator", mfa=True)

    def guard(session):
        appeal_guard(request, actor, session, appeal_id)

    def change(session):
        row = appeal_guard(request, actor, session, appeal_id)
        target, version, _ = appeal_target(
            request,
            actor,
            session,
            row.kind,
            row.target_id,
            True,
            (row.author_id, row.data["original_reviewer"]),
        )
        if (
            row.status != "open"
            or row.version != int(if_match.strip('"'))
            or version != row.target_version
        ):
            raise HTTPException(409)
        if body.outcome == "overturned":
            if row.kind == "review":
                target.status = "rejected" if target.status == "published" else "published"
                target.reviewer_id = str(actor.subject)
                target.data = target.data | {"moderation_reason": body.reason}
            else:
                target.status = "dismissed" if target.status == "upheld" else "upheld"
                session.add(
                    ComplaintDecision(
                        decision_id=str(uuid4()),
                        complaint_id=target.complaint_id,
                        reviewer_id=str(actor.subject),
                        outcome=target.status,
                        reason=body.reason,
                        version=target.version + 1,
                        decided_at=datetime.now(UTC),
                    )
                )
            target.version += 1
        row.status, row.version, row.reviewer_id = body.outcome, row.version + 1, str(actor.subject)
        row.data = row.data | {
            "decision_reason": body.reason,
            "decided_at": datetime.now(UTC).isoformat(),
        }
        return {"appeal_id": row.appeal_id, "status": row.status, "version": row.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"moderation_appeal_decision:{appeal_id}",
        idempotency,
        body.model_dump() | {"version": if_match},
        change,
        guard=guard,
    )


def scrub(session, subject):
    from reverse_hr.coordination.review_sla import scrub as scrub_sla

    scrub_sla(session, "hiring", subject)
    invitations = list(
        session.scalars(
            select(InvitationRow.invitation_id).where(
                (InvitationRow.candidate_id == subject) | (InvitationRow.created_by == subject)
            )
        )
    )
    ids = list(
        session.scalars(
            select(EmployerReview.review_id).where(
                (EmployerReview.author_id == subject)
                | (EmployerReview.reviewer_id == subject)
                | EmployerReview.invitation_id.in_(invitations)
            )
        )
    )
    from reverse_hr.services.hiring.domain.hiring_dialogs import Complaint

    ids += list(
        session.scalars(
            select(Complaint.complaint_id).where(
                (Complaint.author_id == subject) | Complaint.dialog_id.in_(invitations)
            )
        )
    )
    ids += list(
        session.scalars(
            select(ComplaintDecision.complaint_id).where(ComplaintDecision.reviewer_id == subject)
        )
    )
    from reverse_hr.shared.db import IdempotencyRecord

    appeal_ids = list(
        session.scalars(
            select(ModerationAppeal.appeal_id).where(ModerationAppeal.target_id.in_(ids))
        )
    )
    for key in ids + appeal_ids:
        session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.operation.contains(key) | IdempotencyRecord.response.contains(key)
            )
        )
    session.execute(
        delete(ModerationAppeal).where(
            (ModerationAppeal.author_id == subject)
            | (ModerationAppeal.reviewer_id == subject)
            | cast(ModerationAppeal.data, String).contains(subject)
            | ModerationAppeal.target_id.in_(ids)
        )
    )
    session.execute(delete(EmployerReview).where(EmployerReview.review_id.in_(ids)))


@router.get("/employer-reviews")
def review_queue(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("company_moderator", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(EmployerReview).where(EmployerReview.status == "pending")
        if after:
            query = query.where(EmployerReview.review_id > str(after))
        ids = list(session.scalars(query.order_by(EmployerReview.review_id).limit(50)))
        result = []
        for row in ids:
            try:
                row = review_guard(request, actor, session, row.review_id, True)
            except HTTPException as exc:
                if exc.status_code in {403, 404, 409}:
                    continue
                raise
            if row.status == "pending":
                result.append(view(row) | {"status": row.status})
        return result


@router.get("/moderation-appeals")
def appeal_queue(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("company_moderator", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(ModerationAppeal).where(ModerationAppeal.status == "open")
        if after:
            query = query.where(ModerationAppeal.appeal_id > str(after))
        rows = list(session.scalars(query.order_by(ModerationAppeal.appeal_id).limit(50)))
        result = []
        for row in rows:
            try:
                row = appeal_guard(request, actor, session, row.appeal_id)
            except HTTPException as exc:
                if exc.status_code in {403, 404, 409}:
                    continue
                raise
            if row.status == "open":
                result.append(
                    {
                        "appeal_id": row.appeal_id,
                        "kind": row.kind,
                        "due_at": row.data["due_at"],
                        "version": row.version,
                    }
                )
        return result
