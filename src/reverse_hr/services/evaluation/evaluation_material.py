"""Prepare private rubrics; no model calls, source execution, evidence or scoring."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.services.evaluation.domain.evaluation import EvaluationIntake, subject_lock
from reverse_hr.shared.db import enqueue


def prepare_one(engine, access, *, now=None, max_attempts=5, retry_seconds=5):
    if not 1 <= max_attempts <= 10 or not 1 <= retry_seconds <= 300:
        raise ValueError("Invalid preparation retry policy")
    eligible_at = now or datetime.now(UTC)
    with Session(engine) as session:
        row = session.scalar(
            select(EvaluationIntake)
            .where(
                EvaluationIntake.status.in_(["awaiting_material", "material_retry"]),
                or_(
                    EvaluationIntake.material_available_at.is_(None),
                    EvaluationIntake.material_available_at <= eligible_at,
                ),
            )
            .order_by(EvaluationIntake.received_at, EvaluationIntake.stage_id)
            .limit(1)
        )
        if row is None:
            return False
        refs = {
            key: UUID(getattr(row, key))
            for key in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
        }
        version = row.version
    # No local row/subject lock is held during either network request.
    material, failure = None, None
    try:
        material = access.fetch(**refs)
        access.check_assessment(refs["candidate_id"], material.consent_id)
    except HTTPException as exc:
        failure = "denied" if exc.status_code == 409 else "unavailable"
    completed_at = now or datetime.now(UTC)
    with Session(engine) as session, session.begin():
        subject = subject_lock(session, refs["candidate_id"], allow_blocked=True)
        row = session.scalar(
            select(EvaluationIntake)
            .where(EvaluationIntake.stage_id == str(refs["stage_id"]))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if subject.blocked or row is None or row.version != version:
            return True
        row.material_attempts += 1
        row.version += 1
        row.material_available_at = None
        if failure:
            row.status = (
                "material_blocked"
                if failure == "denied"
                else "material_unavailable"
                if row.material_attempts >= max_attempts
                else "material_retry"
            )
            if row.status == "material_retry":
                row.material_available_at = completed_at + timedelta(
                    seconds=min(300, retry_seconds * 2 ** (row.material_attempts - 1))
                )
            return True
        row.material = material.model_dump(mode="json")
        row.status = "material_ready"
        enqueue(
            session,
            EventEnvelope(
                event_type="evaluation.material_ready.v1",
                producer="evaluation",
                correlation_id=uuid4(),
                aggregate_id=refs["stage_id"],
                aggregate_version=row.version,
                payload=refs,
            ),
        )
        return True
