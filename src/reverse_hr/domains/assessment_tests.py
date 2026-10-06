"""Private immutable test suites; human review does not certify sandbox execution."""

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import ValidationError
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, func, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import enqueue
from reverse_hr.domains.assessment import (
    AssessmentBase,
    ContentPackage,
    ContentRevision,
    ReviewCommand,
)
from reverse_hr.domains.assessment_sessions import subject_lock
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import canonical
from reverse_hr.test_suites import SuiteDefinition, digest


class TestSuite(AssessmentBase):
    __tablename__ = "test_suites"
    __table_args__ = (UniqueConstraint("revision_id", "task_key", "number"),)
    suite_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("content_revisions.revision_id"))
    task_key: Mapped[str] = mapped_column(String(64))
    number: Mapped[int]
    definition: Mapped[dict] = mapped_column(JSON)
    definition_digest: Mapped[str] = mapped_column(String(64))
    content_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_reason: Mapped[str | None] = mapped_column(String(2000))
    retired_by: Mapped[str | None] = mapped_column(String(36))
    retirement_reason: Mapped[str | None] = mapped_column(String(2000))


class SuiteView(Contract):
    suite_id: UUID
    revision_id: UUID
    task_key: str
    number: int
    definition: SuiteDefinition
    definition_digest: str
    content_digest: str
    source_dataset: str
    source_version: str
    status: Literal["draft", "reviewed", "retired"]
    version: int
    created_at: datetime
    demo: Literal[True] = True
    runtime_validated: Literal[False] = False
    scoring_enabled: Literal[False] = False


router = APIRouter(prefix="/v1", tags=["assessment-test-suites"])


def pinned(session, revision_id, task_key, definition, *, active):
    row = session.scalar(
        select(ContentRevision)
        .where(ContentRevision.revision_id == str(revision_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404)
    if row.published_at is None or (active and row.status != "published"):
        raise HTTPException(409)
    try:
        package = ContentPackage.model_validate(row.content)
    except ValidationError as exc:
        raise HTTPException(409, "Corrupted content pins") from exc
    task = next((task for task in package.tasks if task.key == task_key), None)
    if task is None:
        raise HTTPException(404)
    if task.format != definition.format:
        raise HTTPException(409, "Suite format differs from pinned task")
    criteria = {item.key for item in task.rubric if item.evidence == "test_result"}
    if not criteria or {case.criterion_key for case in definition.cases} != criteria:
        raise HTTPException(409, "Cases must cover exactly the test_result criteria")
    entry = "main.py" if task.format == "code" else "query.sql"
    if (
        next(file.content for file in definition.reference.files if file.path == entry)
        != task.reference_answer
    ):
        raise HTTPException(409, "Reference differs from pinned task answer")
    return package


def view(session, suite_id):
    row = session.get(TestSuite, str(suite_id), populate_existing=True)
    if row is None:
        raise HTTPException(404)
    try:
        definition = SuiteDefinition.model_validate(row.definition)
    except ValidationError as exc:
        raise HTTPException(409, "Corrupted suite definition") from exc
    package = pinned(session, row.revision_id, row.task_key, definition, active=False)
    if (
        digest(definition) != row.definition_digest
        or hashlib.sha256(canonical(package)).hexdigest() != row.content_digest
    ):
        raise HTTPException(409, "Corrupted suite pins")
    return SuiteView(
        suite_id=row.suite_id,
        revision_id=row.revision_id,
        task_key=row.task_key,
        number=row.number,
        definition=definition,
        definition_digest=row.definition_digest,
        content_digest=row.content_digest,
        source_dataset=package.source_dataset,
        source_version=package.source_version,
        status=row.status,
        version=row.version,
        created_at=row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
    ).model_dump(mode="json")


def guard(request, session, actor):
    subject_lock(session, actor.subject)
    request.app.state.processing_access.check(actor.subject)


def emit(session, request, row, action):
    enqueue(
        session,
        EventEnvelope(
            event_type=f"assessment.test_suite_{action}.v1",
            producer="assessment",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(row.suite_id),
            aggregate_version=row.version,
            payload={"suite_id": UUID(row.suite_id), "revision_id": UUID(row.revision_id)},
        ),
    )


@router.post(
    "/content-versions/{revision_id}/tasks/{task_key}/test-suites",
    response_model=SuiteView,
    status_code=201,
)
def create(
    request: Request,
    actor: Actor,
    revision_id: UUID,
    task_key: Annotated[str, Path(pattern=r"^[a-z][a-z0-9_]{0,63}$")],
    body: SuiteDefinition,
    idempotency: CommandKey,
):
    actor.require("content_admin", mfa=True)

    def change(session):
        package = pinned(session, revision_id, task_key, body, active=True)
        number = (
            session.scalar(
                select(func.max(TestSuite.number)).where(
                    TestSuite.revision_id == str(revision_id), TestSuite.task_key == task_key
                )
            )
            or 0
        )
        row = TestSuite(
            suite_id=str(uuid4()),
            revision_id=str(revision_id),
            task_key=task_key,
            number=number + 1,
            definition=body.model_dump(mode="json"),
            definition_digest=digest(body),
            content_digest=hashlib.sha256(canonical(package)).hexdigest(),
            status="draft",
            version=1,
            created_by=str(actor.subject),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        session.flush()
        emit(session, request, row, "created")
        return {"suite_id": row.suite_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"create_test_suite:{revision_id}:{task_key}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: guard(request, session, actor),
        present=lambda session, result: view(session, result["suite_id"]),
    )


@router.get("/test-suites/{suite_id}", response_model=SuiteView)
def get(request: Request, actor: Actor, suite_id: UUID):
    actor.require("content_admin", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        guard(request, session, actor)
        return view(session, suite_id)


def transition(request, actor, suite_id, body, idempotency, if_match, *, retire):
    expected = int(if_match.strip('"'))
    action = "retired" if retire else "reviewed"

    def change(session):
        row = session.scalar(
            select(TestSuite).where(TestSuite.suite_id == str(suite_id)).with_for_update()
        )
        if row is None:
            raise HTTPException(404)
        if row.version != expected or row.status not in (
            {"draft", "reviewed"} if retire else {"draft"}
        ):
            raise HTTPException(409)
        if not retire and row.created_by == str(actor.subject):
            raise HTTPException(403)
        view(session, suite_id)
        pinned(
            session,
            row.revision_id,
            row.task_key,
            SuiteDefinition.model_validate(row.definition),
            active=not retire,
        )
        values = (
            {"retired_by": str(actor.subject), "retirement_reason": body.reason}
            if retire
            else {"reviewed_by": str(actor.subject), "review_reason": body.reason}
        )
        changed = session.execute(
            update(TestSuite)
            .where(
                TestSuite.suite_id == str(suite_id),
                TestSuite.version == expected,
                TestSuite.status == row.status,
            )
            .values(**values, status=action, version=expected + 1)
        )
        if changed.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        emit(session, request, row, action)
        return {"suite_id": row.suite_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"{action}_test_suite:{suite_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": expected},
        change,
        guard=lambda session: guard(request, session, actor),
        present=lambda session, result: view(session, result["suite_id"]),
    )


@router.post("/test-suites/{suite_id}/review", response_model=SuiteView)
def review(
    request: Request,
    actor: Actor,
    suite_id: UUID,
    body: ReviewCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)
    return transition(request, actor, suite_id, body, idempotency, if_match, retire=False)


@router.post("/test-suites/{suite_id}/retire", response_model=SuiteView)
def retire(
    request: Request,
    actor: Actor,
    suite_id: UUID,
    body: ReviewCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)
    return transition(request, actor, suite_id, body, idempotency, if_match, retire=True)
