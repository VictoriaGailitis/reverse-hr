"""Collect verified source and pending rubric requirements; never infer a score."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from reverse_hr.db import enqueue
from reverse_hr.domains.evaluation import EvaluationIntake, subject_lock
from reverse_hr.evaluation_access import PinnedMaterial
from reverse_hr.events import EventEnvelope


def collect_one(
    engine, material_access, artifact_access, *, now=None, max_attempts=5, retry_seconds=5
):
    if not 1 <= max_attempts <= 10 or not 1 <= retry_seconds <= 300:
        raise ValueError("Invalid artifact retry policy")
    eligible_at = now or datetime.now(UTC)
    with Session(engine) as session:
        row = session.scalar(
            select(EvaluationIntake)
            .where(
                EvaluationIntake.status.in_(["material_ready", "artifact_retry"]),
                or_(
                    EvaluationIntake.artifact_available_at.is_(None),
                    EvaluationIntake.artifact_available_at <= eligible_at,
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
        pinned = PinnedMaterial.model_validate(row.material)
        version = row.version
    source, failure = None, None
    try:
        # Fresh admission also catches cancelled sessions and stale/private material pins.
        current = material_access.fetch(**refs)
        if current != pinned:
            raise HTTPException(503)
        source = artifact_access.fetch(
            **refs,
            format=pinned.task.format,
            snapshot_version=pinned.snapshot_version,
            digest=pinned.snapshot_digest,
        )
        material_access.check_assessment(refs["candidate_id"], pinned.consent_id)
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
        row.artifact_attempts += 1
        row.version += 1
        row.artifact_available_at = None
        if failure:
            row.status = (
                "artifact_blocked"
                if failure == "denied"
                else "artifact_unavailable"
                if row.artifact_attempts >= max_attempts
                else "artifact_retry"
            )
            if row.status == "artifact_retry":
                row.artifact_available_at = completed_at + timedelta(
                    seconds=min(300, retry_seconds * 2 ** (row.artifact_attempts - 1))
                )
            return True
        row.source = source.model_dump(mode="json")
        row.requirements = [
            {
                "criterion_key": c.key,
                "competency": c.competency,
                "max_points": c.points,
                "evidence_type": c.evidence,
                "status": "pending",
                "points": None,
                "snapshot_id": str(refs["snapshot_id"]),
                "digest": pinned.snapshot_digest,
            }
            for c in pinned.task.rubric
        ]
        row.status = "artifact_ready"
        enqueue(
            session,
            EventEnvelope(
                event_type="evaluation.artifact_ready.v1",
                producer="evaluation",
                correlation_id=uuid4(),
                aggregate_id=refs["stage_id"],
                aggregate_version=row.version,
                payload=refs,
            ),
        )
        return True
