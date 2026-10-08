"""Shared fencing and receipt verification, with data owned by each environment."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.db import enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.market_state import lock
from reverse_hr.processing_access import canonical, fresh, sign, verify
from reverse_hr.snapshot_access import SNAPSHOT_REQUEST, SNAPSHOT_RESPONSE, SnapshotReceipt


def owned(request, session, actor, model, subject_model, ref, *, purpose="read"):
    actor.require("candidate")
    lock(session, subject_model, actor.subject)
    row = session.scalar(
        select(model)
        .where(model.id == str(ref))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.candidate_id != str(actor.subject):
        raise HTTPException(404)
    request.app.state.processing_access.check(actor.subject)
    format = request.app.state.stage_access.check_stage(
        actor.subject, UUID(row.session_id), UUID(row.stage_id), purpose
    )
    if format != row.format:
        raise HTTPException(409)
    if hasattr(row, "consent_id"):
        request.app.state.recording_access.check_recording(actor.subject, UUID(row.consent_id))
    return row


def emit(session, request, row, kind):
    service = request.app.state.settings.service_name
    enqueue(
        session,
        EventEnvelope(
            producer=service,
            event_type=f"{service}.{kind}.v1",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(row.id),
            aggregate_version=row.version,
            payload={
                "candidate_id": UUID(row.candidate_id),
                "session_id": UUID(row.session_id),
                "stage_id": UUID(row.stage_id),
                "artifact_id": UUID(row.id),
            },
        ),
    )


def receipt(request, body, signature, nonce_model, subject_model, resolve):
    from reverse_hr.event_transport import Signatures

    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "practical_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, "assessment", signature, SNAPSHOT_REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(nonce_model).where(nonce_model.expires_at < now))
            session.add(nonce_model(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            subject = lock(session, subject_model, body.candidate_id, allow_blocked=True)
            result = None
            if not subject.blocked:
                request.app.state.processing_access.check(body.candidate_id)
                result = resolve(session, body)
            status = SnapshotReceipt(
                **(body.model_dump() | {"issued_at": now}),
                allowed=result is not None,
                **(result or {}),
            )
            response_signature = sign(signatures, SNAPSHOT_RESPONSE, status)
        return Response(
            content=canonical(status),
            media_type="application/json",
            headers={"X-HR-Signature": response_signature, "Cache-Control": "no-store"},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
