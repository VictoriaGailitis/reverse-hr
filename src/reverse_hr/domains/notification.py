"""Idempotent in-app service notices; no message bodies, email, or advertising."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import String, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import IdempotencyRecord, consume_once
from reverse_hr.market_contracts import NoticeView
from reverse_hr.market_state import SubjectColumns, lock


class NotificationBase(DeclarativeBase):
    pass


class NotificationSubject(SubjectColumns, NotificationBase):
    __tablename__ = "notification_subjects"


class NotificationRow(NotificationBase):
    __tablename__ = "notification_notices"
    notice_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recipient_id: Mapped[str] = mapped_column(String(36), index=True)
    invitation_id: Mapped[str] = mapped_column(String(36), index=True)
    creator_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    read: Mapped[bool]
    version: Mapped[int]


class Preference(NotificationBase):
    __tablename__ = "notification_preferences"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    in_app: Mapped[bool]
    version: Mapped[int]


class PreferenceCommand(Contract):
    in_app: bool = Field(strict=True)


class PreferenceView(PreferenceCommand):
    version: int


class NotificationView(Contract):
    notice_id: UUID
    invitation_id: UUID
    kind: str
    read: bool
    version: int


router = APIRouter(prefix="/v1/notifications", tags=["notification"])


def preference(session, subject):
    row = session.get(Preference, str(subject))
    return PreferenceView(
        in_app=row.in_app if row else True, version=row.version if row else 1
    ).model_dump(mode="json")


def available(request, row):
    receipt = request.app.state.market_access.fetch(
        "hiring", "notice", candidate_id=UUID(row.recipient_id), notice_id=UUID(row.notice_id)
    )
    if not receipt.allowed:
        return False
    notice = NoticeView.model_validate(receipt.data)
    if (
        str(notice.invitation_id),
        str(notice.creator_id),
        str(notice.candidate_id),
        str(notice.author_id),
        notice.kind,
    ) != (row.invitation_id, row.creator_id, row.candidate_id, row.author_id, row.kind):
        raise HTTPException(503)
    return True


def view(row):
    return NotificationView(
        notice_id=row.notice_id,
        invitation_id=row.invitation_id,
        kind=row.kind,
        read=row.read,
        version=row.version,
    ).model_dump(mode="json")


@router.get("/preferences", response_model=PreferenceView)
def get_preferences(request: Request, actor: Actor):
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, NotificationSubject, actor.subject)
        return preference(session, actor.subject)


@router.put("/preferences", response_model=PreferenceView)
def set_preferences(
    request: Request,
    actor: Actor,
    body: PreferenceCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        lock(session, NotificationSubject, actor.subject)

    def change(session):
        if preference(session, actor.subject)["version"] != int(if_match.strip('"')):
            raise HTTPException(409)
        row = session.get(Preference, str(actor.subject))
        if row is None:
            row = Preference(subject=str(actor.subject), in_app=body.in_app, version=2)
            session.add(row)
        else:
            row.in_app, row.version = body.in_app, row.version + 1
        return {"subject": str(actor.subject)}

    return execute(
        request.app.state.engine,
        actor.subject,
        "notice_preferences",
        idempotency,
        {"in_app": body.in_app, "version": if_match},
        change,
        guard=guard,
        present=lambda session, _: preference(session, actor.subject),
    )


@router.get("", response_model=list[NotificationView])
def list_notices(request: Request, actor: Actor, after: UUID | None = None):
    with Session(request.app.state.engine) as session, session.begin():
        query = select(NotificationRow).where(NotificationRow.recipient_id == str(actor.subject))
        if after:
            query = query.where(NotificationRow.notice_id > str(after))
        rows = list(session.scalars(query.order_by(NotificationRow.notice_id).limit(50)))
        subjects = {str(actor.subject)} | {
            subject
            for row in rows
            for subject in (row.recipient_id, row.candidate_id, row.author_id, row.creator_id)
        }
        states = {
            subject: lock(session, NotificationSubject, subject, allow_blocked=True)
            for subject in sorted(subjects)
        }
        if states[str(actor.subject)].blocked:
            raise HTTPException(409)
        if not preference(session, actor.subject)["in_app"]:
            return []
        return [
            view(row)
            for row in rows
            if not any(
                states[subject].blocked
                for subject in (row.recipient_id, row.candidate_id, row.author_id, row.creator_id)
            )
            and available(request, row)
        ]


@router.post("/{notice_id}/read", response_model=NotificationView)
def mark_read(
    request: Request,
    actor: Actor,
    notice_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        row = session.get(NotificationRow, str(notice_id))
        if row is None or row.recipient_id != str(actor.subject):
            raise HTTPException(404)
        for subject in sorted({row.recipient_id, row.candidate_id, row.author_id, row.creator_id}):
            lock(session, NotificationSubject, subject)
        row = session.scalar(
            select(NotificationRow)
            .where(NotificationRow.notice_id == str(notice_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise HTTPException(404)
        if not available(request, row):
            raise HTTPException(409)

    def change(session):
        row = session.get(NotificationRow, str(notice_id))
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        if not row.read:
            row.read, row.version = True, row.version + 1
        return {"notice_id": str(notice_id)}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"notice_read:{notice_id}",
        idempotency,
        {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: view(session.get(NotificationRow, str(notice_id))),
    )


def process_notice(session, event, access):
    if (
        event.producer != "hiring"
        or event.event_type != "hiring.notification_requested.v1"
        or set(event.payload)
        != {
            "notice_id",
            "recipient_id",
            "invitation_id",
            "candidate_id",
            "organization_id",
            "actor_id",
            "creator_id",
        }
        or event.aggregate_id != event.payload["notice_id"]
        or event.aggregate_version != 1
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)
    receipt = access.fetch(
        "hiring",
        "notice",
        candidate_id=event.payload["recipient_id"],
        notice_id=event.payload["notice_id"],
    )
    notice = NoticeView.model_validate(receipt.data) if receipt.allowed else None
    if notice and (
        notice.invitation_id != event.payload["invitation_id"]
        or notice.creator_id != event.payload["creator_id"]
        or notice.candidate_id != event.payload["candidate_id"]
        or notice.author_id != event.payload["actor_id"]
    ):
        raise HTTPException(409)

    def apply(session, event):
        subjects = {
            str(event.payload[key])
            for key in ("recipient_id", "candidate_id", "actor_id", "creator_id")
        }
        states = [
            lock(session, NotificationSubject, subject, allow_blocked=True)
            for subject in sorted(subjects)
        ]
        row = session.get(NotificationRow, str(event.payload["notice_id"]))
        if notice is None or any(state.blocked for state in states):
            if row:
                session.delete(row)
            return
        if row:
            if (
                row.recipient_id,
                row.invitation_id,
                row.creator_id,
                row.candidate_id,
                row.author_id,
                row.kind,
            ) != (
                str(notice.recipient_id),
                str(notice.invitation_id),
                str(notice.creator_id),
                str(notice.candidate_id),
                str(notice.author_id),
                notice.kind,
            ):
                raise HTTPException(409)
            return
        session.add(
            NotificationRow(
                notice_id=str(notice.notice_id),
                recipient_id=str(notice.recipient_id),
                invitation_id=str(notice.invitation_id),
                creator_id=str(notice.creator_id),
                candidate_id=str(notice.candidate_id),
                author_id=str(notice.author_id),
                kind=notice.kind,
                read=False,
                version=1,
            )
        )

    return consume_once(session, "notification.notice", event, apply)


def process_deletion_request(session, event):
    from reverse_hr.market_cleanup import erase

    def scrub(subject):
        affected = list(
            session.scalars(
                select(NotificationRow.notice_id).where(
                    (NotificationRow.recipient_id == subject)
                    | (NotificationRow.candidate_id == subject)
                    | (NotificationRow.author_id == subject)
                    | (NotificationRow.creator_id == subject)
                )
            )
        )
        session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.operation.in_([f"notice_read:{ref}" for ref in affected])
            )
        )
        session.execute(
            delete(NotificationRow).where(
                (NotificationRow.recipient_id == subject)
                | (NotificationRow.candidate_id == subject)
                | (NotificationRow.author_id == subject)
                | (NotificationRow.creator_id == subject)
            )
        )
        session.execute(delete(Preference).where(Preference.subject == subject))

    return erase(session, event, "notification", NotificationSubject, scrub)
