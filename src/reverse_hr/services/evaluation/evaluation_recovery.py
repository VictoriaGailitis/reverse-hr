"""Explicit bounded collection retry after evidence becomes available."""

from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from reverse_hr.contracts.core import Contract
from reverse_hr.services.evaluation.domain.evaluation import EvaluationIntake, subject_lock
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute


class RetryView(Contract):
    stage_id: UUID
    status: str
    version: int


router = APIRouter(prefix="/v1/evaluation-reviews", tags=["evaluation-recovery"])


@router.post("/stages/{stage_id}/collection-retry", response_model=RetryView)
def retry(
    request: Request,
    actor: Actor,
    stage_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("assessment_reviewer", mfa=True)

    def guard(session):
        row = session.get(EvaluationIntake, str(stage_id))
        if row is None:
            raise HTTPException(404)
        if row.candidate_id == str(actor.subject):
            raise HTTPException(403)
        for owner in sorted({row.candidate_id, str(actor.subject)}):
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))
        row = session.scalar(
            select(EvaluationIntake)
            .where(EvaluationIntake.stage_id == str(stage_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        material = request.app.state.material_access.fetch(
            **{
                k: UUID(getattr(row, k))
                for k in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
            }
        )
        request.app.state.processing_access.check_assessment(
            UUID(row.candidate_id), material.consent_id
        )
        if row.material != material.model_dump(mode="json"):
            raise HTTPException(409)

    def change(session):
        row = session.get(EvaluationIntake, str(stage_id))
        if (
            row.version != int(if_match.strip('"'))
            or row.status not in {"artifact_retry", "artifact_unavailable", "material_ready"}
            or row.source is not None
            or row.review_number
        ):
            raise HTTPException(409)
        row.status = "material_ready"
        row.version += 1
        row.artifact_attempts = 0
        row.artifact_available_at = None
        return {"stage_id": row.stage_id}

    def present(session, result):
        row = session.get(EvaluationIntake, result["stage_id"])
        return RetryView(stage_id=row.stage_id, status=row.status, version=row.version).model_dump(
            mode="json"
        )

    return execute(
        request.app.state.engine,
        actor.subject,
        f"collection_retry:{stage_id}",
        idempotency,
        {"version": if_match},
        change,
        guard=guard,
        present=present,
    )
