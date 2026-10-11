"""Idempotent in-app service notices; no message bodies, email, or advertising."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_serializer
from sqlalchemy import DateTime, String, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.market_contracts import AppealNoticeView, CompanyNoticeView, NoticeView
from reverse_hr.protocols.market_state import SubjectColumns, lock
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord, consume_once


class NotificationBase(DeclarativeBase):
    pass


class NotificationSubject(SubjectColumns, NotificationBase):
    __tablename__ = "notification_subjects"


class NotificationRow(NotificationBase):
    __tablename__ = "notification_notices"
    notice_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recipient_id: Mapped[str] = mapped_column(String(36), index=True)
    invitation_id: Mapped[str | None] = mapped_column(String(36), index=True)
    assignment_id: Mapped[str | None] = mapped_column(String(36), index=True)
    appeal_id: Mapped[str | None] = mapped_column(String(36), index=True)
    application_id: Mapped[str | None] = mapped_column(String(36), index=True)
    owner: Mapped[str] = mapped_column(String(16), default="hiring")
    category: Mapped[str] = mapped_column(String(16), default="service")
    creator_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    read: Mapped[bool]
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(UTC)
    )


class Preference(NotificationBase):
    __tablename__ = "notification_preferences"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    in_app: Mapped[bool]
    marketing_in_app: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int]


class PreferenceCommand(Contract):
    in_app: bool = Field(strict=True)
    marketing_in_app: bool | None = Field(default=None, strict=True)


class PreferenceView(PreferenceCommand):
    marketing_in_app: bool = False
    version: int


class NotificationView(Contract):
    notice_id: UUID
    invitation_id: UUID | None = None
    assignment_id: UUID | None = None
    application_id: UUID | None = None
    appeal_id: UUID | None = None
    category: str = "service"
    kind: str
    read: bool
    version: int

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        result = handler(self)
        if self.appeal_id is None:
            result.pop("appeal_id", None)
        else:
            result.pop("invitation_id", None)
        if self.application_id is None:
            result.pop("application_id", None)
        if self.assignment_id is None:
            result.pop("assignment_id", None)
        if (
            self.assignment_id is None
            and self.application_id is None
            and self.appeal_id is None
            and self.kind != "task_available"
        ):
            result.pop("category", None)
        else:
            result.pop("invitation_id", None)
        return result


router = APIRouter(prefix="/v1/notifications", tags=["notification"])


def preference(session, subject):
    row = session.get(Preference, str(subject))
    return PreferenceView(
        in_app=row.in_app if row else True,
        marketing_in_app=row.marketing_in_app if row else False,
        version=row.version if row else 1,
    ).model_dump(mode="json")


def available(request, row, *, channel="in_app"):
    if row.owner == "appeal":
        with Session(request.app.state.engine) as db:
            if channel == "in_app" and not preference(db, row.recipient_id)["in_app"]:
                return False
        receipt = request.app.state.market_access.fetch(
            "assessment",
            "appeal-notice",
            candidate_id=UUID(row.recipient_id),
            notice_id=UUID(row.notice_id),
        )
        if not receipt.allowed:
            return False
        notice = AppealNoticeView.model_validate(receipt.data)
        if (
            str(notice.appeal_id),
            str(notice.candidate_id),
            str(notice.author_id),
            notice.kind,
        ) != (row.appeal_id, row.candidate_id, row.author_id, row.kind):
            raise HTTPException(503)
        return True
    if row.owner == "candidate":
        with Session(request.app.state.engine) as db:
            pref = preference(db, row.recipient_id)
        if channel == "in_app" and (not pref["in_app"] or not pref["marketing_in_app"]):
            return False
        receipt = request.app.state.market_access.fetch(
            "candidate",
            "task-notice",
            candidate_id=UUID(row.recipient_id),
            notice_id=UUID(row.notice_id),
        )
        if not receipt.allowed:
            return False
        if receipt.data != {
            "notice_id": row.notice_id,
            "recipient_id": row.recipient_id,
            "kind": "task_available",
            "category": "marketing",
        }:
            raise HTTPException(503)
        return True
    if row.owner == "assessment":
        with Session(request.app.state.engine) as db:
            pref = preference(db, row.recipient_id)
        if channel == "in_app" and (
            not pref["in_app"] or (row.category == "marketing" and not pref["marketing_in_app"])
        ):
            return False
        receipt = request.app.state.market_access.fetch(
            "assessment",
            "company-notice",
            candidate_id=UUID(row.recipient_id),
            notice_id=UUID(row.notice_id),
        )
        if not receipt.allowed:
            return False
        notice = CompanyNoticeView.model_validate(receipt.data)
        if (
            str(notice.assignment_id),
            str(notice.creator_id),
            str(notice.candidate_id),
            str(notice.author_id),
            notice.kind,
            notice.category,
        ) != (
            row.assignment_id,
            row.creator_id,
            row.candidate_id,
            row.author_id,
            row.kind,
            row.category,
        ):
            raise HTTPException(503)
        return True
    receipt = request.app.state.market_access.fetch(
        "hiring", "notice", candidate_id=UUID(row.recipient_id), notice_id=UUID(row.notice_id)
    )
    if not receipt.allowed:
        return False
    notice = NoticeView.model_validate(receipt.data)
    if (
        str(notice.invitation_id),
        str(notice.application_id) if notice.application_id else None,
        str(notice.creator_id),
        str(notice.candidate_id),
        str(notice.author_id),
        notice.kind,
    ) != (
        str(row.invitation_id),
        row.application_id,
        row.creator_id,
        row.candidate_id,
        row.author_id,
        row.kind,
    ):
        raise HTTPException(503)
    return True


def view(row):
    return NotificationView(
        notice_id=row.notice_id,
        invitation_id=row.invitation_id,
        assignment_id=row.assignment_id,
        application_id=row.application_id,
        appeal_id=row.appeal_id,
        category=row.category,
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
            row = Preference(
                subject=str(actor.subject),
                in_app=body.in_app,
                marketing_in_app=body.marketing_in_app or False,
                version=2,
            )
            session.add(row)
        else:
            row.in_app, row.version = body.in_app, row.version + 1
            if body.marketing_in_app is not None:
                row.marketing_in_app = body.marketing_in_app
        return {"subject": str(actor.subject)}

    return execute(
        request.app.state.engine,
        actor.subject,
        "notice_preferences",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
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
    reference = "application_id" if "application_id" in event.payload else "invitation_id"
    if (
        event.producer != "hiring"
        or event.event_type != "hiring.notification_requested.v1"
        or set(event.payload)
        != {
            "notice_id",
            "recipient_id",
            reference,
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
        getattr(notice, reference) != event.payload[reference]
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
                row.application_id,
                row.creator_id,
                row.candidate_id,
                row.author_id,
                row.kind,
            ) != (
                str(notice.recipient_id),
                str(notice.invitation_id) if notice.invitation_id else None,
                str(notice.application_id) if notice.application_id else None,
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
                invitation_id=str(notice.invitation_id) if notice.invitation_id else None,
                application_id=str(notice.application_id) if notice.application_id else None,
                creator_id=str(notice.creator_id),
                candidate_id=str(notice.candidate_id),
                author_id=str(notice.author_id),
                kind=notice.kind,
                read=False,
                version=1,
            )
        )

    return consume_once(session, "notification.notice", event, apply)


def process_company_notice(session, event, access):
    required = {
        "notice_id",
        "assignment_id",
        "candidate_id",
        "recipient_id",
        "organization_id",
        "creator_id",
    }
    if (
        event.producer != "assessment"
        or event.event_type != "assessment.company_notification_requested.v1"
        or set(event.payload) != required
        or event.aggregate_id != event.payload["notice_id"]
        or event.aggregate_version != 1
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)
    receipt = access.fetch(
        "assessment",
        "company-notice",
        candidate_id=event.payload["recipient_id"],
        notice_id=event.payload["notice_id"],
    )
    notice = CompanyNoticeView.model_validate(receipt.data) if receipt.allowed else None
    if notice and any(getattr(notice, key) != event.payload[key] for key in required):
        raise HTTPException(409)

    def apply(session, _):
        subjects = {
            str(event.payload[key]) for key in ("candidate_id", "creator_id", "recipient_id")
        }
        states = [
            lock(session, NotificationSubject, key, allow_blocked=True) for key in sorted(subjects)
        ]
        row = session.get(NotificationRow, str(event.payload["notice_id"]))
        if notice is None or any(state.blocked for state in states):
            if row:
                session.delete(row)
            return
        values = dict(
            notice_id=str(notice.notice_id),
            recipient_id=str(notice.recipient_id),
            invitation_id=None,
            assignment_id=str(notice.assignment_id),
            creator_id=str(notice.creator_id),
            candidate_id=str(notice.candidate_id),
            author_id=str(notice.author_id),
            kind=notice.kind,
            owner="assessment",
            category=notice.category,
        )
        if row:
            if any(getattr(row, key) != value for key, value in values.items()):
                raise HTTPException(409)
            return
        session.add(NotificationRow(**values, read=False, version=1))

    return consume_once(session, "notification.company_notice", event, apply)


def process_deletion_request(session, event):
    from reverse_hr.protocols.market_cleanup import erase

    def scrub(subject):
        from reverse_hr.services.notification.domain.notification_delivery import purge

        purge(session, subject)
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


def process_appeal_notice(session, event, access):
    fields = {"notice_id", "appeal_id", "candidate_id", "author_id"}
    if (
        event.producer != "assessment"
        or event.event_type != "assessment.appeal_notification_requested.v1"
        or set(event.payload) != fields
        or event.aggregate_id != event.payload["notice_id"]
        or event.aggregate_version != 1
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)
    receipt = access.fetch(
        "assessment",
        "appeal-notice",
        candidate_id=event.payload["candidate_id"],
        notice_id=event.payload["notice_id"],
    )
    notice = AppealNoticeView.model_validate(receipt.data) if receipt.allowed else None
    if notice and (
        notice.recipient_id != notice.candidate_id
        or any(getattr(notice, key) != event.payload[key] for key in fields)
    ):
        raise HTTPException(409)

    def apply(session, _):
        subjects = sorted({str(event.payload["candidate_id"]), str(event.payload["author_id"])})
        states = [
            lock(session, NotificationSubject, subject, allow_blocked=True) for subject in subjects
        ]
        row = session.get(NotificationRow, str(event.payload["notice_id"]))
        if notice is None or any(state.blocked for state in states):
            if row:
                session.delete(row)
            return
        values = dict(
            notice_id=str(notice.notice_id),
            appeal_id=str(notice.appeal_id),
            recipient_id=str(notice.recipient_id),
            candidate_id=str(notice.candidate_id),
            creator_id=str(notice.candidate_id),
            author_id=str(notice.author_id),
            kind=notice.kind,
            owner="appeal",
            category="service",
        )
        if row:
            if any(getattr(row, key) != value for key, value in values.items()):
                raise HTTPException(409)
            return
        session.add(NotificationRow(**values, read=False, version=1))

    return consume_once(session, "notification.appeal_notice", event, apply)


def process_task_notice(session, event, access):
    if (
        event.producer != "candidate"
        or event.event_type != "candidate.task_notification_requested.v1"
        or set(event.payload) != {"notice_id", "recipient_id"}
        or event.aggregate_id != event.payload["notice_id"]
        or event.aggregate_version != 1
    ):
        raise HTTPException(409)
    receipt = access.fetch(
        "candidate",
        "task-notice",
        candidate_id=event.payload["recipient_id"],
        notice_id=event.payload["notice_id"],
    )
    expected = dict(
        notice_id=str(event.payload["notice_id"]),
        recipient_id=str(event.payload["recipient_id"]),
        kind="task_available",
        category="marketing",
    )
    if receipt.allowed and receipt.data != expected:
        raise HTTPException(409)

    def apply(session, _):
        subject = str(event.payload["recipient_id"])
        state = lock(session, NotificationSubject, subject, allow_blocked=True)
        row = session.get(NotificationRow, str(event.aggregate_id))
        if not receipt.allowed or state.blocked:
            if row:
                session.delete(row)
            return
        if row is None:
            session.add(
                NotificationRow(
                    notice_id=str(event.aggregate_id),
                    recipient_id=subject,
                    creator_id=subject,
                    candidate_id=subject,
                    author_id=subject,
                    owner="candidate",
                    category="marketing",
                    kind="task_available",
                    read=False,
                    version=1,
                )
            )

    return consume_once(session, "notification.task_notice", event, apply)
