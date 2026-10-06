"""Immutable demo content; publication requires a separate human reviewer."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract, Grade
from reverse_hr.db import enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import canonical


class AssessmentBase(DeclarativeBase):
    pass


class ContentFamily(AssessmentBase):
    __tablename__ = "content_families"
    family_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    specialization: Mapped[str] = mapped_column(String(100))
    grade: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]


class ContentRevision(AssessmentBase):
    __tablename__ = "content_revisions"
    __table_args__ = (UniqueConstraint("family_id", "number"),)
    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    family_id: Mapped[str] = mapped_column(ForeignKey("content_families.family_id"), index=True)
    number: Mapped[int]
    content: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_reason: Mapped[str | None] = mapped_column(String(2000))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    retired_by: Mapped[str | None] = mapped_column(String(36))
    retirement_reason: Mapped[str | None] = mapped_column(String(2000))
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Competency(Contract):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class Criterion(Contract):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    competency: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    description: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    points: int = Field(strict=True, ge=1, le=100)
    evidence: Literal["test_result", "artifact", "timestamped_recording", "board_snapshot"]


class Task(Contract):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    format: Literal["code", "sql", "vcv", "voice", "whiteboard"]
    instruction: str = Field(min_length=1, max_length=20000, pattern=r"\S")
    duration_seconds: int = Field(strict=True, ge=60, le=3600)
    reference_answer: str = Field(min_length=1, max_length=20000, pattern=r"\S")
    rubric: list[Criterion] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid_rubric(self):
        if len({item.key for item in self.rubric}) != len(self.rubric):
            raise ValueError("Criterion keys must be unique within each task")
        if sum(item.points for item in self.rubric) != 100:
            raise ValueError("Each task rubric must total 100 points")
        allowed_evidence = {
            "code": {"test_result", "artifact"},
            "sql": {"test_result", "artifact"},
            "voice": {"timestamped_recording"},
            "whiteboard": {"board_snapshot", "timestamped_recording"},
            "vcv": {"artifact", "timestamped_recording", "board_snapshot"},
        }
        if any(item.evidence not in allowed_evidence[self.format] for item in self.rubric):
            raise ValueError("Evidence must match the practical task format")
        return self


class ContentPackage(Contract):
    specialization: str = Field(min_length=1, max_length=100, pattern=r"\S")
    grade: Grade
    source_dataset: str = Field(min_length=1, max_length=100, pattern=r"\S")
    source_version: str = Field(min_length=1, max_length=100, pattern=r"\S")
    demo: Literal[True] = True
    competencies: list[Competency] = Field(min_length=1, max_length=20)
    tasks: list[Task] = Field(min_length=1, max_length=20)

    @field_validator("demo", mode="before")
    @classmethod
    def demo_only(cls, value):
        if value is not True:
            raise ValueError("Only explicit demo content is currently supported")
        return value

    @model_validator(mode="after")
    def valid_manifest(self):
        keys = {item.key for item in self.competencies}
        references = {item.competency for task in self.tasks for item in task.rubric}
        if len(keys) != len(self.competencies) or references != keys:
            raise ValueError("Unique competencies must exactly match rubric references")
        if len({task.key for task in self.tasks}) != len(self.tasks):
            raise ValueError("Task keys must be unique")
        if sum(task.duration_seconds for task in self.tasks) > 7200:
            raise ValueError("Content duration exceeds two hours")
        if len(canonical(self)) > 262144:
            raise ValueError("Content exceeds bounded package size")
        return self


class FamilyCommand(Contract):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    content: ContentPackage


class FamilyView(Contract):
    family_id: UUID
    name: str
    specialization: str
    grade: Grade
    version: int


class RevisionView(Contract):
    revision_id: UUID
    family_id: UUID
    number: int
    content: ContentPackage
    status: Literal["draft", "published", "retired"]
    version: int
    created_at: datetime
    published_at: datetime | None
    retired_at: datetime | None


class ReviewCommand(Contract):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


router = APIRouter(prefix="/v1", tags=["assessment-content"])


def revision_view(row):
    def utc(value):
        return value.replace(tzinfo=UTC) if value and value.tzinfo is None else value

    return RevisionView(
        revision_id=row.revision_id,
        family_id=row.family_id,
        number=row.number,
        content=row.content,
        status=row.status,
        version=row.version,
        created_at=utc(row.created_at),
        published_at=utc(row.published_at),
        retired_at=utc(row.retired_at),
    ).model_dump(mode="json")


def revision(session, family_id, number, body, actor):
    row = ContentRevision(
        revision_id=str(uuid4()),
        family_id=str(family_id),
        number=number,
        content=body.model_dump(mode="json"),
        status="draft",
        version=1,
        created_by=str(actor.subject),
        created_at=datetime.now(UTC),
    )
    session.add(row)
    return row


def event(session, request, row, name):
    enqueue(
        session,
        EventEnvelope(
            event_type=f"assessment.content_{name}.v1",
            producer="assessment",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(row.revision_id),
            aggregate_version=row.version,
            payload={"revision_id": UUID(row.revision_id), "family_id": UUID(row.family_id)},
        ),
    )


@router.post("/content-families", response_model=RevisionView, status_code=201)
def create_family(request: Request, actor: Actor, body: FamilyCommand, idempotency: CommandKey):
    actor.require("content_admin", mfa=True)

    def change(session):
        family = ContentFamily(
            family_id=str(uuid4()),
            name=body.name,
            specialization=body.content.specialization,
            grade=body.content.grade.value,
            version=1,
        )
        session.add(family)
        session.flush()
        row = revision(session, family.family_id, 1, body.content, actor)
        event(session, request, row, "created")
        return revision_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_content_family",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@router.get("/content-families/{family_id}", response_model=FamilyView)
def get_family(request: Request, actor: Actor, family_id: UUID):
    actor.require("content_admin", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(ContentFamily, str(family_id))
        if row is None:
            raise HTTPException(404)
        return FamilyView(
            family_id=row.family_id,
            name=row.name,
            specialization=row.specialization,
            grade=row.grade,
            version=row.version,
        )


@router.post("/content-families/{family_id}/versions", response_model=RevisionView, status_code=201)
def new_version(
    request: Request,
    actor: Actor,
    family_id: UUID,
    body: ContentPackage,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)
    expected = int(if_match.strip('"'))

    def change(session):
        family = session.get(ContentFamily, str(family_id))
        if family is None:
            raise HTTPException(404)
        if body.specialization != family.specialization or body.grade.value != family.grade:
            raise HTTPException(409)
        updated = session.execute(
            update(ContentFamily)
            .where(
                ContentFamily.family_id == str(family_id),
                ContentFamily.version == expected,
            )
            .values(version=expected + 1)
        )
        if updated.rowcount != 1:
            raise HTTPException(409)
        row = revision(session, family_id, expected + 1, body, actor)
        event(session, request, row, "created")
        return revision_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"new_content_version:{family_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": expected},
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@router.get("/content-versions/{revision_id}", response_model=RevisionView)
def get_revision(request: Request, actor: Actor, revision_id: UUID):
    actor.require("content_admin", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(ContentRevision, str(revision_id))
        if row is None:
            raise HTTPException(404)
        return revision_view(row)


def transition(request, actor, revision_id, body, idempotency, if_match, *, retire):
    expected = int(if_match.strip('"'))

    def change(session):
        row = session.scalar(
            select(ContentRevision)
            .where(
                ContentRevision.revision_id == str(revision_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise HTTPException(404)
        if row.version != expected or row.status != ("published" if retire else "draft"):
            raise HTTPException(409)
        if not retire and row.created_by == str(actor.subject):
            raise HTTPException(403)
        now = datetime.now(UTC)
        if retire:
            values = dict(
                status="retired",
                retired_by=str(actor.subject),
                retirement_reason=body.reason,
                retired_at=now,
            )
        else:
            values = dict(
                status="published",
                reviewed_by=str(actor.subject),
                review_reason=body.reason,
                published_at=now,
            )
        changed = session.execute(
            update(ContentRevision)
            .where(
                ContentRevision.revision_id == str(revision_id),
                ContentRevision.version == expected,
                ContentRevision.status == ("published" if retire else "draft"),
            )
            .values(**values, version=expected + 1)
        )
        if changed.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        event(session, request, row, row.status)
        return revision_view(row)

    operation = "retire" if retire else "publish"
    return execute(
        request.app.state.engine,
        actor.subject,
        f"{operation}_content:{revision_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": expected},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@router.post("/content-versions/{revision_id}/publish", response_model=RevisionView)
def publish(
    request: Request,
    actor: Actor,
    revision_id: UUID,
    body: ReviewCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)
    return transition(request, actor, revision_id, body, idempotency, if_match, retire=False)


@router.post("/content-versions/{revision_id}/retire", response_model=RevisionView)
def retire(
    request: Request,
    actor: Actor,
    revision_id: UUID,
    body: ReviewCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)
    return transition(request, actor, revision_id, body, idempotency, if_match, retire=True)


def subject_lock(session, subject):
    from reverse_hr.domains.assessment_sessions import subject_lock as lock

    return lock(session, subject)
