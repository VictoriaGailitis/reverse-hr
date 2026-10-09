"""Sequential timed code/SQL demo stages; submitted never means evaluated or graded."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.domains.assessment_sessions import (
    PracticalSession,
    SessionView,
    StageState,
    emit,
    session_view,
    subject_lock,
    utc,
)


class SubmissionCommand(Contract):
    workspace_id: UUID
    snapshot_id: UUID


router = APIRouter(prefix="/v1", tags=["assessment-lifecycle"])


def owned(session, actor, session_id):
    row = session.get(PracticalSession, str(session_id))
    if row is None or row.candidate_id != str(actor.subject):
        raise HTTPException(404)
    return row


def command(request, actor, session_id, key, expected, kind, payload, change):
    def guard(session):
        subject_lock(session, actor.subject)
        row = owned(session, actor, session_id)
        request.app.state.processing_access.check_assessment(actor.subject, UUID(row.consent_id))

    return execute(
        request.app.state.engine,
        actor.subject,
        f"{kind}:{session_id}",
        key,
        {"version": expected, **payload},
        change,
        guard=guard,
        present=lambda session, _: session_view(owned(session, actor, session_id)),
    )


@router.post("/assessment-sessions/{session_id}/start", response_model=SessionView)
def start_session(
    request: Request,
    actor: Actor,
    session_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def change(session):
        row = owned(session, actor, session_id)
        if row.status != "preflight" or row.version != expected:
            raise HTTPException(409)
        for position, stage in enumerate(row.stages):
            session.add(
                StageState(
                    stage_id=stage["stage_id"],
                    session_id=row.session_id,
                    position=position,
                    status="pending",
                    version=1,
                )
            )
        row.status, row.version, row.current_stage_id = (
            "in_progress",
            row.version + 1,
            row.stages[0]["stage_id"],
        )
        emit(
            session,
            request,
            row.session_id,
            row.version,
            "session_started",
            {"candidate_id": actor.subject, "session_id": session_id},
        )
        return session_view(row)

    return command(request, actor, session_id, idempotency, expected, "start_session", {}, change)


@router.post(
    "/assessment-sessions/{session_id}/stages/{stage_id}/start", response_model=SessionView
)
def start_stage(
    request: Request,
    actor: Actor,
    session_id: UUID,
    stage_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def change(session):
        row = owned(session, actor, session_id)
        if (
            row.status != "in_progress"
            or row.version != expected
            or row.current_stage_id != str(stage_id)
        ):
            raise HTTPException(409)
        stage = session.get(StageState, str(stage_id))
        if stage is None or stage.session_id != row.session_id:
            raise HTTPException(404)
        spec = next(s for s in row.stages if s["stage_id"] == str(stage_id))
        if spec.get("follows_stage_id"):
            parent = session.get(StageState, spec["follows_stage_id"])
            if parent is None or parent.status != "submitted":
                raise HTTPException(409, "The initial solution must be submitted first")
        if stage.status != "pending" or spec["format"] not in {
            "code",
            "sql",
            "vcv",
            "voice",
            "whiteboard",
        }:
            raise HTTPException(409)
        stage.status, stage.version, stage.started_at = "active", 2, datetime.now(UTC)
        stage.deadline = stage.started_at + timedelta(seconds=spec["duration_seconds"])
        row.version += 1
        emit(
            session,
            request,
            stage.stage_id,
            stage.version,
            "stage_started",
            {"candidate_id": actor.subject, "session_id": session_id, "stage_id": stage_id},
        )
        return session_view(row)

    return command(
        request, actor, session_id, idempotency, expected, f"start_stage:{stage_id}", {}, change
    )


@router.post(
    "/assessment-sessions/{session_id}/stages/{stage_id}/submit", response_model=SessionView
)
def submit_stage(
    request: Request,
    actor: Actor,
    session_id: UUID,
    stage_id: UUID,
    body: SubmissionCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def change(session):
        row = owned(session, actor, session_id)
        if (
            row.status != "in_progress"
            or row.version != expected
            or row.current_stage_id != str(stage_id)
        ):
            raise HTTPException(409)
        stage = session.get(StageState, str(stage_id))
        if stage is None or stage.session_id != row.session_id:
            raise HTTPException(404)
        if stage.status != "active" or datetime.now(UTC) >= utc(stage.deadline):
            raise HTTPException(409)
        spec = next(s for s in row.stages if s["stage_id"] == str(stage_id))
        access = (
            request.app.state.snapshot_access
            if spec["format"] in {"code", "sql"}
            else request.app.state.practical_receipt_access
        )
        args = {} if spec["format"] in {"code", "sql"} else {"format": spec["format"]}
        receipt = access.fetch(
            actor.subject, session_id, stage_id, body.workspace_id, body.snapshot_id, **args
        )
        if receipt.format != spec["format"] or datetime.now(UTC) >= utc(stage.deadline):
            raise HTTPException(409)
        stage.status, stage.version, stage.submitted_at = "submitted", 3, datetime.now(UTC)
        stage.workspace_id, stage.snapshot_id = str(body.workspace_id), str(body.snapshot_id)
        stage.snapshot_version, stage.digest = receipt.snapshot_version, receipt.digest
        row.version += 1
        next_stage = session.scalar(
            select(StageState).where(
                StageState.session_id == row.session_id, StageState.position == stage.position + 1
            )
        )
        row.current_stage_id = next_stage.stage_id if next_stage else None
        if next_stage is None:
            row.status = "submitted"
        emit(
            session,
            request,
            stage.stage_id,
            stage.version,
            "stage_submitted",
            {
                "candidate_id": actor.subject,
                "session_id": session_id,
                "stage_id": stage_id,
                "workspace_id": body.workspace_id,
                "snapshot_id": body.snapshot_id,
            },
        )
        if row.status == "submitted":
            emit(
                session,
                request,
                row.session_id,
                row.version,
                "session_submitted",
                {
                    "candidate_id": actor.subject,
                    "session_id": session_id,
                    "plan_version_id": UUID(row.plan_version_id),
                },
            )
            from reverse_hr.domains.company_schedules import queue_result

            queue_result(session, row)
        return session_view(row)

    return command(
        request,
        actor,
        session_id,
        idempotency,
        expected,
        f"submit_stage:{stage_id}",
        body.model_dump(mode="json"),
        change,
    )
