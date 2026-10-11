"""Accepted invitation dialogs and minimal, privately exported notice references."""

from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.market_contracts import MarketReceipt, MarketRequest, NoticeView
from reverse_hr.protocols.market_access import Signature, respond
from reverse_hr.protocols.market_state import lock
from reverse_hr.services.hiring.domain.hiring import (
    HiringBase,
    HiringNonce,
    HiringSubject,
    InvitationRow,
    emit,
    internal_router,
    invitation_guard,
    router,
    utc,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord, Outbox


class Dialog(HiringBase):
    __tablename__ = "hiring_dialogs"
    dialog_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int]
    sequence: Mapped[int]


class EmployerBlock(HiringBase):
    __tablename__ = "hiring_employer_blocks"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), primary_key=True)


class Message(HiringBase):
    __tablename__ = "hiring_messages"
    __table_args__ = (UniqueConstraint("dialog_id", "sequence"),)
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dialog_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    text: Mapped[str] = mapped_column(String(4000))
    sequence: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Complaint(HiringBase):
    __tablename__ = "hiring_complaints"
    complaint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dialog_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    message_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Notice(HiringBase):
    __tablename__ = "hiring_notices"
    notice_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    invitation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    application_id: Mapped[str | None] = mapped_column(String(36), index=True)
    recipient_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))


class MessageCommand(Contract):
    text: str = Field(min_length=1, max_length=4000, pattern=r"\S")


class MessageView(MessageCommand):
    message_id: UUID
    dialog_id: UUID
    author_id: UUID
    sequence: int
    created_at: datetime


class DialogView(Contract):
    dialog_id: UUID
    organization_id: UUID
    candidate_id: UUID
    blocked: bool
    version: int
    last_sequence: int


class ComplaintCommand(Contract):
    message_id: UUID | None = None
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class ComplaintView(ComplaintCommand):
    complaint_id: UUID
    dialog_id: UUID
    created_at: datetime


def blocked(session, candidate, organization):
    return session.get(EmployerBlock, (str(candidate), str(organization))) is not None


def notify(session, request, invitation, recipient, kind, author):
    row = Notice(
        notice_id=str(uuid4()),
        invitation_id=invitation.invitation_id,
        recipient_id=str(recipient),
        author_id=str(author),
        kind=kind,
    )
    session.add(row)
    emit(
        session,
        request,
        row.notice_id,
        1,
        "notification_requested",
        {
            "notice_id": UUID(row.notice_id),
            "recipient_id": UUID(str(recipient)),
            "invitation_id": UUID(invitation.invitation_id),
            "candidate_id": UUID(invitation.candidate_id),
            "organization_id": UUID(invitation.organization_id),
            "actor_id": UUID(str(author)),
            "creator_id": UUID(invitation.created_by),
        },
    )


def open_dialog(session, row):
    # Same transaction as acceptance; invitation ID is the natural uniqueness key.
    session.add(Dialog(dialog_id=row.invitation_id, version=1, sequence=0))


def dialog_guard(request, actor, dialog_id, session, *, communication=True, authors=()):
    row = invitation_guard(request, actor, dialog_id, session, subjects=authors)
    dialog = session.scalar(
        select(Dialog)
        .where(Dialog.dialog_id == str(dialog_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if dialog is None or row.status != "accepted":
        raise HTTPException(404)
    if communication:
        if blocked(session, row.candidate_id, row.organization_id):
            raise HTTPException(409)
        request.app.state.market_access.require(
            "privacy",
            "contact-permission",
            candidate_id=UUID(row.candidate_id),
            organization_id=UUID(row.organization_id),
            invitation_id=dialog_id,
        )
    return row, dialog


def dialog_view(session, row, dialog):
    return DialogView(
        dialog_id=dialog.dialog_id,
        organization_id=row.organization_id,
        candidate_id=row.candidate_id,
        version=dialog.version,
        last_sequence=dialog.sequence,
        blocked=blocked(session, row.candidate_id, row.organization_id),
    ).model_dump(mode="json")


def message_view(row):
    return MessageView(
        message_id=row.message_id,
        dialog_id=row.dialog_id,
        author_id=row.author_id,
        text=row.text,
        sequence=row.sequence,
        created_at=utc(row.created_at),
    ).model_dump(mode="json")


@router.get("/dialogs/{dialog_id}", response_model=DialogView)
def get_dialog(request: Request, actor: Actor, dialog_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row, dialog = dialog_guard(request, actor, dialog_id, session, communication=False)
        return dialog_view(session, row, dialog)


@router.get("/dialogs/{dialog_id}/messages", response_model=list[MessageView])
def messages(request: Request, actor: Actor, dialog_id: UUID, after: int = 0):
    if after < 0:
        raise HTTPException(422)
    with Session(request.app.state.engine) as session, session.begin():
        rows = list(
            session.scalars(
                select(Message)
                .where(Message.dialog_id == str(dialog_id), Message.sequence > after)
                .order_by(Message.sequence)
                .limit(50)
            )
        )
        dialog_guard(request, actor, dialog_id, session, authors={m.author_id for m in rows})
        for row in rows:
            request.app.state.processing_access.check(UUID(row.author_id))
        return [message_view(row) for row in rows]


@router.post("/dialogs/{dialog_id}/messages", response_model=MessageView, status_code=201)
def send_message(
    request: Request,
    actor: Actor,
    dialog_id: UUID,
    body: MessageCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        dialog_guard(request, actor, dialog_id, session)

    def change(session):
        row, dialog = dialog_guard(request, actor, dialog_id, session)
        if dialog.version != int(if_match.strip('"')):
            raise HTTPException(409)
        dialog.sequence += 1
        dialog.version += 1
        msg = Message(
            message_id=str(uuid4()),
            dialog_id=str(dialog_id),
            author_id=str(actor.subject),
            text=body.text,
            sequence=dialog.sequence,
            created_at=datetime.now(UTC),
        )
        session.add(msg)
        from reverse_hr.services.hiring.domain.hiring_communication_risk import screen

        screen(session, request, row, msg)
        notify(
            session,
            request,
            row,
            row.created_by if str(actor.subject) == row.candidate_id else row.candidate_id,
            "dialog_message",
            actor.subject,
        )
        session.flush()
        return {"message_id": msg.message_id}

    def present(session, result):
        msg = session.get(Message, result["message_id"])
        if msg is None or msg.dialog_id != str(dialog_id):
            raise HTTPException(404)
        return message_view(msg)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"message:{dialog_id}",
        idempotency,
        {"text": body.text, "version": if_match},
        change,
        201,
        guard=guard,
        present=present,
    )


@router.post("/dialogs/{dialog_id}/block", response_model=DialogView)
def block_employer(
    request: Request,
    actor: Actor,
    dialog_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        row, _ = dialog_guard(request, actor, dialog_id, session, communication=False)
        if row.candidate_id != str(actor.subject):
            raise HTTPException(403)
        actor.require("candidate")

    def change(session):
        row, dialog = dialog_guard(request, actor, dialog_id, session, communication=False)
        if dialog.version != int(if_match.strip('"')):
            raise HTTPException(409)
        if not blocked(session, row.candidate_id, row.organization_id):
            session.add(
                EmployerBlock(candidate_id=row.candidate_id, organization_id=row.organization_id)
            )
            dialog.version += 1
        session.flush()
        return {"dialog_id": str(dialog_id)}

    def present(session, _):
        row, dialog = dialog_guard(request, actor, dialog_id, session, communication=False)
        return dialog_view(session, row, dialog)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"block:{dialog_id}",
        idempotency,
        {"version": if_match},
        change,
        guard=guard,
        present=present,
    )


@router.post("/dialogs/{dialog_id}/complaints", response_model=ComplaintView, status_code=201)
def complain(
    request: Request, actor: Actor, dialog_id: UUID, body: ComplaintCommand, idempotency: CommandKey
):
    def guard(session):
        authors = set()
        if body.message_id:
            msg = session.get(Message, str(body.message_id))
            if msg is None or msg.dialog_id != str(dialog_id):
                raise HTTPException(404)
            authors.add(msg.author_id)
        dialog_guard(request, actor, dialog_id, session, communication=False, authors=authors)
        for subject in authors:
            request.app.state.processing_access.check(UUID(subject))

    def change(session):
        row = Complaint(
            complaint_id=str(uuid4()),
            dialog_id=str(dialog_id),
            author_id=str(actor.subject),
            message_id=str(body.message_id) if body.message_id else None,
            reason=body.reason,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        from reverse_hr.services.hiring.domain.hiring_moderation import ComplaintCase

        session.add(ComplaintCase(complaint_id=row.complaint_id, status="open", version=1))
        emit(
            session,
            request,
            row.complaint_id,
            1,
            "complaint_created",
            {
                "complaint_id": UUID(row.complaint_id),
                "invitation_id": dialog_id,
                "candidate_id": UUID(session.get(InvitationRow, str(dialog_id)).candidate_id),
                "actor_id": actor.subject,
            },
        )
        session.flush()
        return {"complaint_id": row.complaint_id}

    def present(session, result):
        row = session.get(Complaint, result["complaint_id"])
        if row is None or row.author_id != str(actor.subject):
            raise HTTPException(404)
        return ComplaintView(
            complaint_id=row.complaint_id,
            dialog_id=row.dialog_id,
            message_id=row.message_id,
            reason=row.reason,
            created_at=utc(row.created_at),
        ).model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"complaint:{dialog_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


@internal_router.post("/notice", response_model=MarketReceipt)
def export_notice(request: Request, body: MarketRequest, signature: Signature):
    def check(session):
        notice = session.get(Notice, str(body.notice_id))
        if notice is None or notice.recipient_id != str(body.candidate_id):
            return None, 0
        if notice.application_id:
            from reverse_hr.services.hiring.domain.hiring_vacancies import application_notice

            return application_notice(request, session, notice)
        row = session.get(InvitationRow, notice.invitation_id)
        if row is None:
            return None, 0
        for subject in sorted(
            {notice.recipient_id, notice.author_id, row.candidate_id, row.created_by}
        ):
            if lock(session, HiringSubject, subject, allow_blocked=True).blocked:
                return None, 0
            request.app.state.processing_access.check(UUID(subject))
        if blocked(session, row.candidate_id, row.organization_id):
            return None, 0
        if notice.recipient_id != row.candidate_id:
            permission = request.app.state.market_access.fetch(
                "employer",
                "membership",
                candidate_id=UUID(notice.recipient_id),
                actor_id=UUID(notice.recipient_id),
                organization_id=UUID(row.organization_id),
            )
            if not permission.allowed:
                return None, 0
        return NoticeView(
            creator_id=row.created_by,
            candidate_id=row.candidate_id,
            author_id=notice.author_id,
            notice_id=notice.notice_id,
            recipient_id=notice.recipient_id,
            invitation_id=row.invitation_id,
            kind=notice.kind,
        ).model_dump(mode="json"), 1

    return respond(
        request, body, signature, "hiring", "notice", HiringNonce, {"notification"}, check
    )


def scrub_dialogs(session, subject):
    from reverse_hr.services.hiring.domain.hiring_communication_risk import scrub as scrub_risks

    scrub_risks(session, subject)
    from reverse_hr.services.hiring.domain.hiring_vacancies import Application

    ids = select(InvitationRow.invitation_id).where(
        (InvitationRow.candidate_id == subject)
        | (InvitationRow.created_by == subject)
        | InvitationRow.invitation_id.in_(
            select(Application.invitation_id).where(Application.created_by == subject)
        )
    )
    affected_ids = list(session.scalars(ids))
    message_condition = Message.dialog_id.in_(affected_ids) | (Message.author_id == subject)
    message_ids = list(session.scalars(select(Message.message_id).where(message_condition)))
    from reverse_hr.services.hiring.domain.hiring_moderation import ComplaintCase, ComplaintDecision

    reviewed = select(ComplaintDecision.complaint_id).where(
        ComplaintDecision.reviewer_id == subject
    )
    complaint_condition = (
        Complaint.complaint_id.in_(reviewed)
        | Complaint.dialog_id.in_(affected_ids)
        | (Complaint.author_id == subject)
        | Complaint.message_id.in_(message_ids)
    )
    complaint_ids = list(session.scalars(select(Complaint.complaint_id).where(complaint_condition)))
    for ref in message_ids + complaint_ids:
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.response.contains(ref)))
    session.execute(
        delete(Outbox).where(Outbox.envelope["aggregate_id"].as_string().in_(complaint_ids))
    )
    notice_ids = list(
        session.scalars(
            select(Notice.notice_id).where(
                Notice.invitation_id.in_(affected_ids)
                | (Notice.recipient_id == subject)
                | (Notice.author_id == subject)
            )
        )
    )
    session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.operation.in_(
                [
                    f"{operation}:{ref}"
                    for ref in affected_ids
                    for operation in ("message", "block", "complaint")
                ]
            )
        )
    )
    session.execute(
        delete(Outbox).where(
            Outbox.envelope["aggregate_id"].as_string().in_(affected_ids + notice_ids)
        )
    )
    session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.operation.in_([f"complaint_decision:{ref}" for ref in complaint_ids])
        )
    )
    session.execute(
        delete(ComplaintDecision).where(ComplaintDecision.complaint_id.in_(complaint_ids))
    )
    session.execute(delete(ComplaintCase).where(ComplaintCase.complaint_id.in_(complaint_ids)))
    session.execute(delete(Complaint).where(Complaint.complaint_id.in_(complaint_ids)))
    session.execute(delete(Message).where(message_condition))
    session.execute(
        delete(Notice).where(
            (Notice.invitation_id.in_(ids))
            | (Notice.recipient_id == subject)
            | (Notice.author_id == subject)
        )
    )
    session.execute(delete(Dialog).where(Dialog.dialog_id.in_(ids)))
    session.execute(delete(EmployerBlock).where(EmployerBlock.candidate_id == subject))
