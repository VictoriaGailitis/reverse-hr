"""Native validation requests received as references, never executable broker payloads."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.protocols.generated_validation import GeneratedValidationAccess
from reverse_hr.services.code_runner.domain.code_runner import RunnerBase, subject_lock
from reverse_hr.services.code_runner.sandbox import SandboxUnavailable
from reverse_hr.services.code_runner.validation_queue import enqueue_validation
from reverse_hr.shared.db import consume_once


class GeneratedValidationIntent(RunnerBase):
    __tablename__ = "runner_generated_validations"
    generation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    validation_id: Mapped[str | None] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def receive(session, event):
    if (
        event.producer != "assessment"
        or event.event_type != "assessment.generated_validation_requested.v1"
        or set(event.payload) != {"candidate_id", "generation_id"}
        or event.aggregate_id != event.payload["generation_id"]
        or event.aggregate_version != 1
    ):
        raise HTTPException(409)

    def apply(session, event):
        owner, generation = str(event.payload["candidate_id"]), str(event.payload["generation_id"])
        subject_lock(session, owner)
        row = session.get(GeneratedValidationIntent, generation)
        if row is not None:
            if row.owner_id != owner:
                raise HTTPException(409)
            return
        session.add(
            GeneratedValidationIntent(
                generation_id=generation,
                owner_id=owner,
                status="pending",
                available_at=datetime.now(UTC),
            )
        )

    return consume_once(session, "runner.generated_validation", event, apply)


def dispatch_one(engine, processing, admission, executor, signatures):
    now = datetime.now(UTC)
    with Session(engine) as session:
        row = session.scalar(
            select(GeneratedValidationIntent)
            .where(
                GeneratedValidationIntent.status == "pending",
                GeneratedValidationIntent.available_at <= now,
            )
            .order_by(GeneratedValidationIntent.available_at)
            .limit(1)
        )
        if row is None:
            return False
        generation_id, owner = row.generation_id, row.owner_id
    access = GeneratedValidationAccess(executor.settings)
    access._signatures = signatures
    try:
        plan = access.fetch(UUID(owner), UUID(generation_id))
        validation_id = enqueue_validation(engine, owner, plan, processing, admission, executor)
    except (HTTPException, SandboxUnavailable) as exc:
        with Session(engine) as session, session.begin():
            row = session.get(GeneratedValidationIntent, generation_id)
            if row:
                row.status = (
                    "cancelled"
                    if isinstance(exc, HTTPException) and exc.status_code == 409
                    else "pending"
                )
                row.available_at = now + timedelta(seconds=30)
        return True
    with Session(engine) as session, session.begin():
        subject_lock(session, owner)
        processing.check(UUID(owner))
        row = session.get(GeneratedValidationIntent, generation_id)
        if row:
            row.validation_id, row.status = str(validation_id), "enqueued"
    return True
