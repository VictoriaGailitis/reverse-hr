"""Candidate-owned opt-in task discovery; durable deduplication and live rights checks."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.market_contracts import MarketRequest, Skills
from reverse_hr.protocols.market_access import Signature, respond
from reverse_hr.services.candidate.domain.candidate import (
    CandidateBase,
    CandidateProfile,
    router,
    specialization_choices,
    subject_lock,
)
from reverse_hr.services.candidate.domain.candidate_grades import current_grade
from reverse_hr.services.candidate.domain.candidate_market import CandidateNonce, Publication
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, execute
from reverse_hr.shared.db import enqueue

SubscriptionVersion = Annotated[str, Header(alias="If-Match", pattern=r'^"[0-9]+"$')]


class TaskSubscription(CandidateBase):
    __tablename__ = "candidate_task_subscriptions"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    enabled: Mapped[bool]
    consent_id: Mapped[str | None] = mapped_column(String(36))
    stack_tags: Mapped[list] = mapped_column(JSON)
    interval_hours: Mapped[int]
    version: Mapped[int]
    catalog_after: Mapped[str | None] = mapped_column(String(36))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class TaskRecommendation(CandidateBase):
    __tablename__ = "candidate_task_recommendations"
    __table_args__ = (UniqueConstraint("candidate_id", "version_id"),)
    notice_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    version_id: Mapped[str] = mapped_column(String(36))
    data: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubscriptionCommand(Skills):
    enabled: bool = Field(strict=True)
    consent_id: UUID | None = None
    interval_hours: int = Field(default=24, strict=True, ge=1, le=168)


def subscription_view(row):
    return dict(
        version=row.version if row else 0,
        enabled=row.enabled if row else False,
        consent_id=row.consent_id if row else None,
        declared_skills=row.stack_tags if row else [],
        interval_hours=row.interval_hours if row else 24,
    )


def consent(request, row):
    if not row.enabled or not row.consent_id:
        raise HTTPException(409, "Task recommendations disabled")
    request.app.state.processing_access.check(UUID(row.candidate_id))
    request.app.state.market_access.require(
        "privacy",
        "purpose-permission",
        candidate_id=UUID(row.candidate_id),
        consent_id=UUID(row.consent_id),
        consent_purpose="task_recommendations",
    )


def matches(session, candidate_id, tags, item):
    profile = session.get(CandidateProfile, str(candidate_id))
    if profile is None:
        return False
    for choice in specialization_choices(profile):
        if choice["specialization"].casefold() != item["specialization"].casefold():
            continue
        # A declared level is an interest only. No task notice confirms a grade.
        grade = (
            current_grade(session, candidate_id, choice["specialization"])
            or choice["declared_grade"]
        )
        if str(getattr(grade, "value", grade)) != item["grade"]:
            continue
        skills = tags
        if not skills:
            publication = session.get(Publication, str(candidate_id))
            skills = publication.declared_skills if publication else []
        required = {tag.casefold() for tag in item.get("stack_tags", [])}
        if required.issubset({tag.casefold() for tag in skills}):
            return True
    return False


@router.get("/me/task-subscription")
def get_subscription(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        row = session.get(TaskSubscription, str(actor.subject))
        value = subscription_view(row)
        if row and row.enabled:
            try:
                consent(request, row)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                value["enabled"] = False
        return value


@router.put("/me/task-subscription")
def update_subscription(
    request: Request,
    actor: Actor,
    body: SubscriptionCommand,
    idempotency: CommandKey,
    if_match: SubscriptionVersion,
):
    actor.require("candidate")
    if body.enabled != (body.consent_id is not None):
        raise HTTPException(422, "Enabled subscription requires its own consent")

    def guard(session):
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)

    def change(session):
        if session.get(CandidateProfile, str(actor.subject)) is None:
            raise HTTPException(404)
        row = session.get(TaskSubscription, str(actor.subject))
        if (row.version if row else 0) != int(if_match.strip('"')):
            raise HTTPException(409)
        if row is None:
            row = TaskSubscription(candidate_id=str(actor.subject), version=0)
            session.add(row)
        row.enabled, row.consent_id = (
            body.enabled,
            str(body.consent_id) if body.consent_id else None,
        )
        row.stack_tags, row.interval_hours = body.declared_skills, body.interval_hours
        row.version += 1
        row.catalog_after, row.available_at = None, datetime.now(UTC)
        if row.enabled:
            consent(request, row)
        return subscription_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "task_subscription",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
        change,
        guard=guard,
        present=lambda session, _: subscription_view(
            session.get(TaskSubscription, str(actor.subject))
        ),
    )


def notice_data(request, session, candidate_id, notice_id):
    subject = subject_lock(session, candidate_id, allow_blocked=True)
    if subject.blocked:
        return None
    row = session.get(TaskRecommendation, str(notice_id))
    sub = session.get(TaskSubscription, str(candidate_id))
    if row is None or row.candidate_id != str(candidate_id) or sub is None:
        return None
    try:
        consent(request, sub)
    except HTTPException as exc:
        if exc.status_code == 409:
            return None
        raise
    receipt = request.app.state.market_access.require(
        "assessment",
        "task-catalog",
        candidate_id=candidate_id,
        catalog_version_id=UUID(row.version_id),
    )
    items = receipt.data["items"]
    if not items or not matches(session, candidate_id, sub.stack_tags, items[0]):
        return None
    return dict(
        notice_id=row.notice_id,
        recipient_id=row.candidate_id,
        kind="task_available",
        category="marketing",
    )


internal_router = APIRouter(prefix="/internal/v1/market")


@internal_router.post("/task-notice")
def task_notice(request: Request, body: MarketRequest, signature: Signature = None):
    return respond(
        request,
        body,
        signature,
        "candidate",
        "task-notice",
        CandidateNonce,
        {"notification"},
        lambda session: (notice_data(request, session, body.candidate_id, body.notice_id), 1),
    )


@router.get("/me/task-recommendations")
def recommendations(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        query = select(TaskRecommendation).where(
            TaskRecommendation.candidate_id == str(actor.subject)
        )
        if after:
            query = query.where(TaskRecommendation.notice_id > str(after))
        rows = list(session.scalars(query.order_by(TaskRecommendation.notice_id).limit(21)))
        return dict(
            items=[
                dict(**row.data, notice_id=row.notice_id, created_at=row.created_at)
                for row in rows[:20]
                if notice_data(request, session, actor.subject, UUID(row.notice_id))
            ],
            next_cursor=rows[19].notice_id if len(rows) > 20 else None,
        )


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def run_one(request, *, now=None):
    now = now or datetime.now(UTC)
    engine = request.app.state.engine
    with Session(engine) as session:
        sub = session.scalar(
            select(TaskSubscription)
            .where(
                TaskSubscription.enabled == True,  # noqa: E712
                TaskSubscription.available_at <= now,
            )
            .order_by(TaskSubscription.available_at)
            .limit(1)
        )
        if sub is None:
            return False
        candidate, version, cursor = UUID(sub.candidate_id), sub.version, sub.catalog_after
        try:
            consent(request, sub)
            receipt = request.app.state.market_access.require(
                "assessment",
                "task-catalog",
                candidate_id=candidate,
                **({"catalog_after": UUID(cursor)} if cursor else {}),
            )
            catalog = receipt.data
        except HTTPException as exc:
            with Session(engine) as db, db.begin():
                state = subject_lock(db, candidate, allow_blocked=True)
                current = db.get(TaskSubscription, str(candidate))
                if current and current.version == version and not state.blocked:
                    if exc.status_code == 409:
                        current.enabled = False
                        current.version += 1
                    current.available_at = now + timedelta(minutes=5)
            return True
    with Session(engine) as session, session.begin():
        state = subject_lock(session, candidate, allow_blocked=True)
        sub = session.get(TaskSubscription, str(candidate))
        if (
            state.blocked
            or sub is None
            or not sub.enabled
            or sub.version != version
            or utc(sub.available_at) > now
        ):
            return True
        # Recheck consent after network I/O, inside the same serialization point
        # as cancellation, profile updates and Privacy deletion.
        try:
            consent(request, sub)
        except HTTPException as exc:
            if exc.status_code != 409:
                sub.available_at = now + timedelta(minutes=5)
                return True
            sub.enabled = False
            sub.version += 1
            return True
        if sub.last_sent_at and utc(sub.last_sent_at) + timedelta(hours=sub.interval_hours) > now:
            sub.available_at = utc(sub.last_sent_at) + timedelta(hours=sub.interval_hours)
            return True
        for item in catalog["items"]:
            if not matches(session, candidate, sub.stack_tags, item):
                continue
            if session.scalar(
                select(TaskRecommendation.notice_id).where(
                    TaskRecommendation.candidate_id == str(candidate),
                    TaskRecommendation.version_id == item["version_id"],
                )
            ):
                continue
            row = TaskRecommendation(
                notice_id=str(uuid4()),
                candidate_id=str(candidate),
                version_id=item["version_id"],
                data=item,
                created_at=now,
            )
            session.add(row)
            sub.last_sent_at, sub.available_at = now, now + timedelta(hours=sub.interval_hours)
            # Stay on this page until its remaining matches have been notified.
            enqueue(
                session,
                EventEnvelope(
                    event_type="candidate.task_notification_requested.v1",
                    producer="candidate",
                    correlation_id=uuid4(),
                    aggregate_id=UUID(row.notice_id),
                    aggregate_version=1,
                    payload={"notice_id": UUID(row.notice_id), "recipient_id": candidate},
                ),
            )
            return True
        sub.catalog_after = catalog["next_cursor"]
        sub.available_at = now + timedelta(seconds=1 if sub.catalog_after else 300)
        return True
