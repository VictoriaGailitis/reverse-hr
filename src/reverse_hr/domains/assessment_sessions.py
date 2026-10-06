"""Pinned demo plans, consent-gated sessions and stage records; no grading yet."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, ForeignKey, String, delete, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column, object_session

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract, Grade
from reverse_hr.db import IdempotencyRecord, Outbox, consume_once, enqueue
from reverse_hr.domains.assessment import AssessmentBase, ContentRevision
from reverse_hr.events import EventEnvelope
from reverse_hr.session_test_pins import (
    PlanPins,
    SessionPins,
    SessionSuitePin,
    TaskSuiteSelection,
    stored_pins,
)
from reverse_hr.test_suites import digest as test_digest


class PlanVersion(AssessmentBase):
    __tablename__ = "plan_versions"
    plan_version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    specialization: Mapped[str] = mapped_column(String(100))
    grade: Mapped[str] = mapped_column(String(16))
    revision_ids: Mapped[list] = mapped_column(JSON)
    stages: Mapped[list] = mapped_column(JSON)
    test_pins: Mapped[list | None] = mapped_column(JSON)
    test_pins_digest: Mapped[str | None] = mapped_column(String(64))
    duration_seconds: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_by: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    review_reason: Mapped[str] = mapped_column(String(2000))
    retired_by: Mapped[str | None] = mapped_column(String(36))
    retirement_reason: Mapped[str | None] = mapped_column(String(2000))


class PracticalSession(AssessmentBase):
    __tablename__ = "assessment_sessions"
    session_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    plan_version_id: Mapped[str] = mapped_column(ForeignKey("plan_versions.plan_version_id"))
    consent_id: Mapped[str] = mapped_column(String(36))
    stages: Mapped[list] = mapped_column(JSON)
    test_pins: Mapped[list | None] = mapped_column(JSON)
    test_pins_digest: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    current_stage_id: Mapped[str | None] = mapped_column(String(36))


class StageState(AssessmentBase):
    __tablename__ = "assessment_stages"
    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    session_id: Mapped[str] = mapped_column(
        ForeignKey("assessment_sessions.session_id"), index=True
    )
    position: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workspace_id: Mapped[str | None] = mapped_column(String(36))
    snapshot_id: Mapped[str | None] = mapped_column(String(36))
    snapshot_version: Mapped[int | None]
    digest: Mapped[str | None] = mapped_column(String(64))


class AssessmentSubject(AssessmentBase):
    __tablename__ = "assessment_subjects"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    status: Mapped[str | None] = mapped_column(String(16))


class PlanCommand(Contract):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    revision_ids: list[UUID] = Field(min_length=1, max_length=10)
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    test_suite_selections: list[TaskSuiteSelection] = Field(default_factory=list, max_length=20)


class PlanView(Contract):
    plan_version_id: UUID
    name: str
    specialization: str
    grade: Grade
    duration_seconds: int
    formats: list[str]
    demo: Literal[True] = True
    status: Literal["published", "retired"]
    version: int


class SessionCommand(Contract):
    plan_version_id: UUID
    assessment_consent_id: UUID


class StageView(Contract):
    stage_id: UUID
    revision_id: UUID
    task_key: str
    format: Literal["code", "sql", "vcv", "voice", "whiteboard"]
    instruction: str
    duration_seconds: int


class SessionSummary(Contract):
    session_id: UUID
    plan_version_id: UUID
    status: Literal["preflight", "in_progress", "submitted", "cancelled"]
    current_stage_id: UUID | None = None
    version: int
    demo: Literal[True] = True


class StageProgress(Contract):
    stage_id: UUID
    status: Literal["pending", "active", "submitted", "cancelled"]
    version: int
    started_at: datetime | None
    deadline: datetime | None
    submitted_at: datetime | None
    workspace_id: UUID | None
    snapshot_id: UUID | None
    snapshot_version: int | None
    digest: str | None


class SessionView(SessionSummary):
    stages: list[StageView]
    progress: list[StageProgress] = Field(default_factory=list)


class ReasonCommand(Contract):
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


router = APIRouter(prefix="/v1", tags=["assessment-sessions"])


def subject_lock(session, subject, *, allow_blocked=False):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(AssessmentSubject)
        .values(subject=str(subject), blocked=False)
        .on_conflict_do_nothing(index_elements=["subject"])
    )
    row = session.scalar(
        select(AssessmentSubject)
        .where(AssessmentSubject.subject == str(subject))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.blocked and not allow_blocked:
        raise HTTPException(409)
    return row


def plan_view(row):
    return PlanView(
        plan_version_id=row.plan_version_id,
        name=row.name,
        specialization=row.specialization,
        grade=row.grade,
        duration_seconds=row.duration_seconds,
        formats=list(dict.fromkeys(stage["format"] for stage in row.stages)),
        status=row.status,
        version=row.version,
    ).model_dump(mode="json")


def utc(value):
    return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def progress_view(row):
    session = object_session(row)
    return [
        StageProgress(
            **{
                key: utc(getattr(stage, key))
                if key in {"started_at", "deadline", "submitted_at"}
                else getattr(stage, key)
                for key in StageProgress.model_fields
            }
        )
        for stage in session.scalars(
            select(StageState)
            .where(StageState.session_id == row.session_id)
            .order_by(StageState.position)
        )
    ]


def session_view(row):
    try:
        stored_pins(row, for_session=True)
    except ValueError as exc:
        raise HTTPException(409, "Corrupted session pins") from exc
    return SessionView(
        session_id=row.session_id,
        plan_version_id=row.plan_version_id,
        status=row.status,
        version=row.version,
        stages=row.stages,
        current_stage_id=row.current_stage_id,
        progress=progress_view(row),
    ).model_dump(mode="json")


def session_summary(row):
    return SessionSummary(
        session_id=row.session_id,
        plan_version_id=row.plan_version_id,
        status=row.status,
        version=row.version,
        current_stage_id=row.current_stage_id,
    ).model_dump(mode="json")


def emit(session, request, aggregate, version, kind, payload):
    enqueue(
        session,
        EventEnvelope(
            event_type=f"assessment.{kind}.v1",
            producer="assessment",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(aggregate),
            aggregate_version=version,
            payload=payload,
        ),
    )


@router.post("/assessment-plans", response_model=PlanView, status_code=201)
def create_plan(request: Request, actor: Actor, body: PlanCommand, idempotency: CommandKey):
    actor.require("content_admin", mfa=True)
    from reverse_hr.domains.assessment_plan_tests import (
        check_pins,
        guard_owners,
        lock_suites,
        resolve,
    )

    def change(session):
        if len(set(body.revision_ids)) != len(body.revision_ids):
            raise HTTPException(422)
        lock_suites(session, body.test_suite_selections)
        rows = {}
        for revision_id in sorted(body.revision_ids):
            row = session.scalar(
                select(ContentRevision)
                .where(ContentRevision.revision_id == str(revision_id))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if row is None:
                raise HTTPException(404)
            if row.status != "published":
                raise HTTPException(409)
            rows[revision_id] = row
        documents = [rows[revision_id].content for revision_id in body.revision_ids]
        if len({(doc["specialization"], doc["grade"]) for doc in documents}) != 1:
            raise HTTPException(409)
        stages = []
        for revision_id in body.revision_ids:
            for task in rows[revision_id].content["tasks"]:
                stages.append(
                    {
                        "revision_id": str(revision_id),
                        "task_key": task["key"],
                        "format": task["format"],
                        "instruction": task["instruction"],
                        "duration_seconds": task["duration_seconds"],
                    }
                )
        duration = sum(stage["duration_seconds"] for stage in stages)
        if len(stages) > 20 or duration > 7200:
            raise HTTPException(422)
        pins = resolve(
            request,
            session,
            body.test_suite_selections,
            stages,
            {revision: row.content for revision, row in rows.items()},
        )
        row = PlanVersion(
            plan_version_id=str(uuid4()),
            name=body.name,
            specialization=documents[0]["specialization"],
            grade=documents[0]["grade"],
            revision_ids=[str(value) for value in body.revision_ids],
            stages=stages,
            test_pins=[pin.model_dump(mode="json") for pin in pins],
            test_pins_digest=test_digest(PlanPins(pins=pins)),
            duration_seconds=duration,
            status="published",
            version=1,
            created_by=str(actor.subject),
            created_at=datetime.now(UTC),
            review_reason=body.reason,
        )
        session.add(row)
        emit(
            session,
            request,
            row.plan_version_id,
            1,
            "plan_published",
            {"plan_version_id": UUID(row.plan_version_id)},
        )
        return {"plan_version_id": row.plan_version_id}

    def guard(session):
        if body.test_suite_selections:
            guard_owners(request, session, actor.subject, body.test_suite_selections)
        else:
            subject_lock(session, actor.subject)

    def present(session, result):
        row = session.get(PlanVersion, result["plan_version_id"])
        if row is None:
            raise HTTPException(404)
        try:
            pins = stored_pins(row)
        except ValueError as exc:
            raise HTTPException(409, "Corrupted plan pins") from exc
        check_pins(request, session, pins, row.stages, current=True)
        return plan_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_assessment_plan",
        idempotency,
        body.model_dump(mode="json", exclude_defaults=True),
        change,
        201,
        guard=guard,
        present=present,
    )


@router.get("/assessment-plans", response_model=list[PlanView])
def list_plans(request: Request, actor: Actor):
    actor.require("candidate")
    from reverse_hr.domains.assessment_plan_tests import check_pins

    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        results = []
        for row in session.scalars(select(PlanVersion).where(PlanVersion.status == "published")):
            if not all(
                session.get(ContentRevision, revision_id).status == "published"
                for revision_id in row.revision_ids
            ):
                continue
            try:
                pins = stored_pins(row)
                check_pins(request, session, pins, row.stages, current=True)
            except ValueError:
                continue
            except HTTPException as exc:
                if exc.status_code not in {404, 409}:
                    raise
                continue
            results.append(plan_view(row))
        return results


@router.post("/assessment-plans/{plan_version_id}/retire", response_model=PlanView)
def retire_plan(
    request: Request,
    actor: Actor,
    plan_version_id: UUID,
    body: ReasonCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)
    expected = int(if_match.strip('"'))

    def change(session):
        row = session.get(PlanVersion, str(plan_version_id))
        if row is None:
            raise HTTPException(404)
        result = session.execute(
            update(PlanVersion)
            .where(
                PlanVersion.plan_version_id == str(plan_version_id),
                PlanVersion.status == "published",
                PlanVersion.version == expected,
            )
            .values(
                status="retired",
                version=expected + 1,
                retired_by=str(actor.subject),
                retirement_reason=body.reason,
            )
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        emit(
            session,
            request,
            row.plan_version_id,
            row.version,
            "plan_retired",
            {"plan_version_id": plan_version_id},
        )
        return plan_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"retire_assessment_plan:{plan_version_id}",
        idempotency,
        {"body": body.model_dump(), "version": expected},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@router.post("/assessment-sessions", response_model=SessionView, status_code=201)
def create_session(request: Request, actor: Actor, body: SessionCommand, idempotency: CommandKey):
    actor.require("candidate")
    from reverse_hr.domains.assessment_plan_tests import check_pins, guard_owners, lock_suites

    def guard(session):
        plan = session.get(PlanVersion, str(body.plan_version_id))
        try:
            pins = stored_pins(plan) if plan else []
        except ValueError as exc:
            raise HTTPException(409, "Corrupted plan pins") from exc
        if pins:
            guard_owners(request, session, actor.subject, pins)
        else:
            subject_lock(session, actor.subject)
        request.app.state.processing_access.check_assessment(
            actor.subject, body.assessment_consent_id
        )

    def change(session):
        if session.scalar(
            select(PracticalSession.session_id)
            .where(
                PracticalSession.candidate_id == str(actor.subject),
                PracticalSession.status.in_(["preflight", "in_progress"]),
            )
            .limit(1)
        ):
            raise HTTPException(409)
        plan = session.scalar(
            select(PlanVersion)
            .where(PlanVersion.plan_version_id == str(body.plan_version_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if plan is None:
            raise HTTPException(404)
        if plan.status != "published":
            raise HTTPException(409)
        try:
            pins = stored_pins(plan)
        except ValueError as exc:
            raise HTTPException(409, "Corrupted plan pins") from exc
        lock_suites(session, pins)
        for revision_id in sorted(plan.revision_ids):
            content = session.scalar(
                select(ContentRevision)
                .where(ContentRevision.revision_id == revision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if content is None or content.status != "published":
                raise HTTPException(409)
        check_pins(request, session, pins, plan.stages, current=True)
        stages = [dict(stage, stage_id=str(uuid4())) for stage in plan.stages]
        session_pins = [
            SessionSuitePin(**pin.model_dump(), stage_id=stages[pin.position]["stage_id"])
            for pin in pins
        ]
        row = PracticalSession(
            session_id=str(uuid4()),
            candidate_id=str(actor.subject),
            plan_version_id=plan.plan_version_id,
            consent_id=str(body.assessment_consent_id),
            stages=stages,
            test_pins=[pin.model_dump(mode="json") for pin in session_pins],
            test_pins_digest=test_digest(SessionPins(pins=session_pins)),
            status="preflight",
            version=1,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        emit(
            session,
            request,
            row.session_id,
            1,
            "session_created",
            {
                "session_id": UUID(row.session_id),
                "candidate_id": actor.subject,
                "plan_version_id": body.plan_version_id,
            },
        )
        return session_view(row)

    def present(session, result):
        row = session.get(PracticalSession, result["session_id"])
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        return session_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_assessment_session",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


@router.get("/assessment-sessions/{session_id}", response_model=SessionView)
def get_session(request: Request, actor: Actor, session_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(PracticalSession, str(session_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        request.app.state.processing_access.check_assessment(actor.subject, UUID(row.consent_id))
        return session_view(row)


@router.post("/assessment-sessions/{session_id}/cancel", response_model=SessionSummary)
def cancel_session(
    request: Request,
    actor: Actor,
    session_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def change(session):
        row = session.get(PracticalSession, str(session_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        result = session.execute(
            update(PracticalSession)
            .where(
                PracticalSession.session_id == str(session_id),
                PracticalSession.version == expected,
                PracticalSession.status.in_(["preflight", "in_progress"]),
            )
            .values(status="cancelled", current_stage_id=None, version=expected + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        session.execute(
            update(StageState)
            .where(
                StageState.session_id == row.session_id,
                StageState.status.in_(["pending", "active"]),
            )
            .values(status="cancelled")
        )
        emit(
            session,
            request,
            row.session_id,
            row.version,
            "session_cancelled",
            {"session_id": session_id, "candidate_id": actor.subject},
        )
        return session_summary(row)

    def present(session, result):
        row = session.get(PracticalSession, str(session_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        return session_summary(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"cancel_assessment_session:{session_id}",
        idempotency,
        {"version": expected},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
        present=present,
    )


def process_deletion_request(session, event):
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        from reverse_hr.domains.assessment_tests import TestSuite
        from reverse_hr.domains.assessment_verdicts import ValidationIntake

        subject = str(event.payload["candidate_id"])
        row = subject_lock(session, subject, allow_blocked=True)
        if row.request_id is not None and row.request_id != str(event.aggregate_id):
            raise HTTPException(409)
        first = row.request_id is None
        row.blocked, row.request_id = True, str(event.aggregate_id)
        session.execute(delete(ValidationIntake).where(ValidationIntake.owner_id == subject))
        session.execute(
            delete(StageState).where(
                StageState.session_id.in_(
                    select(PracticalSession.session_id).where(
                        PracticalSession.candidate_id == subject
                    )
                )
            )
        )
        session.execute(delete(PracticalSession).where(PracticalSession.candidate_id == subject))
        session.execute(
            delete(Outbox).where(
                Outbox.envelope["producer"].as_string() == "assessment",
                Outbox.envelope["payload"]["candidate_id"].as_string() == subject,
                Outbox.envelope["event_type"]
                .as_string()
                .in_(
                    [
                        "assessment.session_created.v1",
                        "assessment.session_started.v1",
                        "assessment.session_cancelled.v1",
                        "assessment.session_submitted.v1",
                        "assessment.stage_started.v1",
                        "assessment.stage_submitted.v1",
                        "assessment.validation_verdict_received.v1",
                        "assessment.runtime_attestation_received.v1",
                    ]
                ),
            )
        )
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == subject))
        retained_content = session.scalar(
            select(ContentRevision.revision_id)
            .where(
                (ContentRevision.created_by == subject)
                | (ContentRevision.reviewed_by == subject)
                | (ContentRevision.retired_by == subject)
            )
            .limit(1)
        )
        retained_plans = session.scalar(
            select(PlanVersion.plan_version_id)
            .where((PlanVersion.created_by == subject) | (PlanVersion.retired_by == subject))
            .limit(1)
        )
        retained_suites = session.scalar(
            select(TestSuite.suite_id)
            .where(
                (TestSuite.created_by == subject)
                | (TestSuite.reviewed_by == subject)
                | (TestSuite.retired_by == subject)
            )
            .limit(1)
        )
        row.status = (
            "restricted" if retained_content or retained_plans or retained_suites else "deleted"
        )
        if first:
            enqueue(
                session,
                EventEnvelope(
                    event_type=f"assessment.data_{row.status}.v1",
                    producer="assessment",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    aggregate_version=1,
                    payload=event.payload,
                ),
            )

    return consume_once(session, "assessment.deletion_request", event, apply)
