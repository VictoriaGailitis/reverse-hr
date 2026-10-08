"""Purpose-bound private exports to Evaluation after current Assessment admission."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.domains.media import MediaNonce, MediaSubject, Recording, assembled
from reverse_hr.domains.whiteboard import (
    Board,
    BoardDocument,
    BoardNonce,
    BoardSnapshot,
    BoardSubject,
)
from reverse_hr.evaluation_artifact_access import (
    ARTIFACT_REQUEST,
    ARTIFACT_RESPONSE,
    MAX_ARTIFACT_BYTES,
    ArtifactReceipt,
    ArtifactRequest,
)
from reverse_hr.market_state import lock
from reverse_hr.media_transcription import Transcript
from reverse_hr.practical_evidence import PracticalSource, TranscriptDocument, sha
from reverse_hr.processing_access import canonical, fresh, sign, verify

router = APIRouter(prefix="/internal/v1", tags=["internal-practical-evidence"])


def matches(session, body, owner):
    if owner == "whiteboard":
        row = session.get(Board, str(body.workspace_id))
        snapshot = session.get(BoardSnapshot, str(body.snapshot_id))
        return (
            row
            if row
            and snapshot
            and row.status == "sealed"
            and snapshot.board_id == row.id
            and snapshot.version == body.snapshot_version
            and snapshot.digest == body.digest
            and row.candidate_id == str(body.candidate_id)
            and row.session_id == str(body.session_id)
            and row.stage_id == str(body.stage_id)
            and body.format == "whiteboard"
            else None
        )
    row = session.get(Recording, str(body.workspace_id))
    return (
        row
        if row
        and row.status == "finalized"
        and row.snapshot_id == str(body.snapshot_id)
        and row.version == body.snapshot_version
        and row.expected_digest == body.digest
        and row.candidate_id == str(body.candidate_id)
        and row.session_id == str(body.session_id)
        and row.stage_id == str(body.stage_id)
        and row.format == body.format
        else None
    )


def export_document(request, session, body, owner):
    row = matches(session, body, owner)
    if row is None:
        return None
    request.app.state.processing_access.check(body.candidate_id)
    if owner == "whiteboard":
        snapshot = session.get(BoardSnapshot, str(body.snapshot_id))
        return PracticalSource(
            snapshot_id=body.snapshot_id,
            format="whiteboard",
            digest=body.digest,
            board=BoardDocument(state=snapshot.state),
        )
    from uuid import UUID

    request.app.state.recording_access.check_recording(body.candidate_id, UUID(row.consent_id))
    assembled(session, row)
    request.app.state.processing_access.check(body.candidate_id)
    request.app.state.recording_access.check_recording(body.candidate_id, UUID(row.consent_id))
    transcript = session.get(Transcript, row.id)
    if transcript is None:
        raise HTTPException(503, "Transcription is not ready")
    document = TranscriptDocument.model_validate(transcript.document)
    if transcript.recording_digest != body.digest or sha(document) != transcript.digest:
        raise HTTPException(409)
    return PracticalSource(
        snapshot_id=body.snapshot_id,
        format=row.format,
        digest=body.digest,
        transcript_id=transcript.transcript_id,
        transcript_digest=transcript.digest,
        transcript=document,
    )


@router.post("/evaluation-artifact", response_model=ArtifactReceipt)
def artifact(
    request: Request,
    body: ArtifactRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.event_transport import Signatures

    owner = request.app.state.settings.service_name
    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "practical_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, "evaluation", signature, ARTIFACT_REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    try:
        # Release owner locks before requesting Assessment; receipt flow uses Assessment -> owner.
        with Session(request.app.state.engine) as session:
            exists = matches(session, body, owner) is not None
        permit = None
        if exists:
            try:
                permit = request.app.state.artifact_permit_access.check(body)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
        now = datetime.now(UTC)
        nonce_model, subject_model = (
            (BoardNonce, BoardSubject) if owner == "whiteboard" else (MediaNonce, MediaSubject)
        )
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(nonce_model).where(nonce_model.expires_at < now))
            session.add(nonce_model(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            subject = lock(session, subject_model, body.candidate_id, allow_blocked=True)
            document = (
                export_document(request, session, body, owner)
                if permit and not subject.blocked
                else None
            )
            if permit and not fresh(permit.issued_at):
                raise HTTPException(503)
            response = ArtifactReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=document is not None,
                manifest=document,
            )
            raw = canonical(response)
            if len(raw) > MAX_ARTIFACT_BYTES:
                raise HTTPException(503)
            signed = sign(signatures, ARTIFACT_RESPONSE, response)
        return Response(
            content=raw,
            media_type="application/json",
            headers={"X-HR-Signature": signed, "Cache-Control": "no-store"},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
