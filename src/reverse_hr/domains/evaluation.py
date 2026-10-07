"""Durable demo intake; artifact references alone never constitute an evaluation."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, delete, literal, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.contracts import Contract
from reverse_hr.db import IdempotencyRecord, Outbox, consume_once, enqueue
from reverse_hr.events import EventEnvelope


class EvaluationBase(DeclarativeBase):
    pass


class EvaluationSubject(EvaluationBase):
    __tablename__ = "evaluation_subjects"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    deletion_request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EvaluationIntake(EvaluationBase):
    __tablename__ = "evaluation_intakes"
    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36))
    snapshot_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(32), default="awaiting_material")
    version: Mapped[int] = mapped_column(default=1)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    material: Mapped[dict | None] = mapped_column(JSON)
    material_attempts: Mapped[int] = mapped_column(default=0)
    material_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source: Mapped[dict | None] = mapped_column(JSON)
    requirements: Mapped[list | None] = mapped_column(JSON)
    artifact_attempts: Mapped[int] = mapped_column(default=0)
    artifact_available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    score: Mapped[int | None]
    review_number: Mapped[int] = mapped_column(default=0)


class IntakeView(Contract):
    stage_id: UUID
    session_id: UUID
    status: Literal[
        "awaiting_material",
        "material_retry",
        "material_ready",
        "material_blocked",
        "material_unavailable",
        "artifact_ready",
        "artifact_retry",
        "artifact_blocked",
        "artifact_unavailable",
        "needs_evidence",
        "reviewed",
    ]
    version: int
    received_at: datetime
    score: int | None = Field(default=None, ge=0, le=100)
    confirmed_grade: None = None
    demo: Literal[True] = True


router = APIRouter(prefix="/v1/evaluations", tags=["evaluation"])


def subject_lock(session, candidate_id, *, allow_blocked=False):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(EvaluationSubject)
        .values(candidate_id=str(candidate_id), blocked=False)
        .on_conflict_do_nothing(index_elements=["candidate_id"])
    )
    row = session.scalar(
        select(EvaluationSubject)
        .where(EvaluationSubject.candidate_id == str(candidate_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.blocked and not allow_blocked:
        raise HTTPException(409)
    return row


@router.get("/stages/{stage_id}", response_model=IntakeView)
def get_intake(request: Request, actor: Actor, stage_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(EvaluationIntake, str(stage_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        if row.material is not None:
            request.app.state.processing_access.check_assessment(
                actor.subject, UUID(row.material["consent_id"])
            )
        received = row.received_at
        if received.tzinfo is None:
            received = received.replace(tzinfo=UTC)
        return IntakeView(
            stage_id=row.stage_id,
            session_id=row.session_id,
            status=row.status,
            version=row.version,
            received_at=received,
            score=row.score,
        )


def process_submission(session, event, access):
    """Signed transport authenticates Assessment; commit inbox, intake and outbox together."""
    fields = {"candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id"}
    if (
        event.producer != "assessment"
        or event.event_type != "assessment.stage_submitted.v1"
        or set(event.payload) != fields
        or event.aggregate_id != event.payload["stage_id"]
        or event.aggregate_version != 3
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = subject_lock(session, event.payload["candidate_id"], allow_blocked=True)
        if subject.blocked:
            return
        # Restrictions can arrive before the deletion event in a different queue.
        try:
            access.check(event.payload["candidate_id"])
        except HTTPException as exc:
            if exc.status_code == 409:
                return
            raise
        refs = {name: str(value) for name, value in event.payload.items()}
        row = session.get(EvaluationIntake, refs["stage_id"])
        if row:
            if any(getattr(row, name) != value for name, value in refs.items()):
                raise HTTPException(409)
            return
        session.add(EvaluationIntake(**refs, received_at=datetime.now(UTC)))
        enqueue(
            session,
            EventEnvelope(
                event_type="evaluation.intake_created.v1",
                producer="evaluation",
                correlation_id=event.correlation_id,
                aggregate_id=event.aggregate_id,
                aggregate_version=1,
                payload=event.payload,
            ),
        )

    return consume_once(session, "evaluation.stage_submission", event, apply)


def process_deletion_request(session, event):
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        from reverse_hr.domains.evaluation_review import ReviewRecord
        from reverse_hr.domains.evaluation_tests import TestEvidence
        from reverse_hr.evaluation_llm import ModelAttempt

        candidate = str(event.payload["candidate_id"])
        request_id = str(event.payload["request_id"])
        subject = subject_lock(session, candidate, allow_blocked=True)
        if subject.deletion_request_id not in {None, request_id}:
            raise HTTPException(409)
        model_interrupts = select(literal("interrupt_model:") + ModelAttempt.attempt_id).where(
            ModelAttempt.candidate_id == candidate
        )
        session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.operation.in_(model_interrupts))
        )
        session.execute(delete(ModelAttempt).where(ModelAttempt.candidate_id == candidate))
        session.execute(delete(TestEvidence).where(TestEvidence.candidate_id == candidate))
        session.execute(delete(ReviewRecord).where(ReviewRecord.candidate_id == candidate))
        operations = select(literal("evaluation_review:") + EvaluationIntake.stage_id).where(
            EvaluationIntake.candidate_id == candidate
        )
        session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.operation.in_(operations))
        )
        model_operations = select(literal("model_attempt:") + EvaluationIntake.stage_id).where(
            EvaluationIntake.candidate_id == candidate
        )
        session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.operation.in_(model_operations))
        )
        session.execute(delete(EvaluationIntake).where(EvaluationIntake.candidate_id == candidate))
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == candidate))
        for row in session.scalars(select(Outbox)).all():
            if (
                row.envelope.get("event_type")
                in {
                    "evaluation.intake_created.v1",
                    "evaluation.material_ready.v1",
                    "evaluation.artifact_ready.v1",
                    "evaluation.review_recorded.v1",
                    "evaluation.test_evidence_received.v1",
                    "evaluation.model_requested.v1",
                    "evaluation.model_started.v1",
                    "evaluation.model_proposal_ready.v1",
                    "evaluation.model_failed.v1",
                    "evaluation.model_interrupted.v1",
                }
                and row.envelope.get("payload", {}).get("candidate_id") == candidate
            ):
                session.delete(row)
        first = subject.deletion_request_id is None
        retained = (
            session.scalar(
                select(ReviewRecord.review_id).where(ReviewRecord.reviewer_id == candidate).limit(1)
            )
            is not None
        ) or session.scalar(
            select(ModelAttempt.attempt_id).where(ModelAttempt.requested_by == candidate).limit(1)
        ) is not None
        previously_restricted = subject.blocked and subject.deleted_at is None
        subject.blocked, subject.deletion_request_id = True, request_id
        subject.deleted_at = None if retained else datetime.now(UTC)
        if first or (previously_restricted and not retained):
            enqueue(
                session,
                EventEnvelope(
                    event_type="evaluation.data_restricted.v1"
                    if retained
                    else "evaluation.data_deleted.v1",
                    producer="evaluation",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    aggregate_version=1,
                    payload=event.payload,
                ),
            )

    return consume_once(session, "evaluation.deletion_request", event, apply)
