"""Private reviewer playback: every chunk repeats live permission and integrity checks."""

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.auth import Actor
from reverse_hr.domains.media import (
    MediaNonce,
    MediaSubject,
    RecordingChunk,
    assembled,
    chunk_bytes,
)
from reverse_hr.evaluation_artifact_access import ArtifactRequest
from reverse_hr.market_state import lock
from reverse_hr.practical_export import matches
from reverse_hr.processing_access import ProcessingAccess, canonical, fresh, sign, verify

REQUEST = b"reverse-hr.recording-playback-request.v1\0"
RESPONSE = b"reverse-hr.recording-playback-response.v1\0"


class PlaybackRequest(ArtifactRequest):
    number: int = Field(strict=True, ge=0, le=127)


class PlaybackReply(PlaybackRequest):
    allowed: bool = Field(strict=True)
    data_base64: str | None = Field(default=None, max_length=349528)
    chunk_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    total_size: int | None = Field(default=None, strict=True, ge=1, le=32 * 1024 * 1024)

    @model_validator(mode="after")
    def bytes(self):
        values = (self.data_base64, self.chunk_digest, self.total_size)
        if (self.allowed and any(v is None for v in values)) or (
            not self.allowed and any(v is not None for v in values)
        ):
            raise ValueError("Invalid playback reply")
        if self.allowed:
            raw = base64.b64decode(self.data_base64, validate=True)
            if (
                self.number * 262144 >= self.total_size
                or len(raw) != min(262144, self.total_size - self.number * 262144)
                or hashlib.sha256(raw).hexdigest() != self.chunk_digest
            ):
                raise ValueError("Invalid playback chunk")
        return self


class PlaybackAccess(ProcessingAccess):
    def fetch(self, body):
        try:
            raw, signature = self._send(
                "recording-playback",
                canonical(body),
                sign(self.signatures, REQUEST, body),
                origin=self.settings.media_api_url,
                max_bytes=512000,
            )
            reply = PlaybackReply.model_validate_json(raw)
            verify(self.signatures, "media", signature, RESPONSE, reply)
            if (
                len(raw) > 512000
                or raw != canonical(reply)
                or not fresh(reply.issued_at)
                or any(
                    getattr(body, k) != getattr(reply, k)
                    for k in type(body).model_fields
                    if k != "issued_at"
                )
            ):
                raise ValueError("Invalid playback binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not reply.allowed:
            raise HTTPException(409)
        return reply


internal_router = APIRouter(prefix="/internal/v1", tags=["internal-recording-playback"])
router = APIRouter(prefix="/v1/evaluation-reviews", tags=["reviewer-recording-playback"])


@internal_router.post("/recording-playback", response_model=PlaybackReply)
def playback(
    request: Request,
    body: PlaybackRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
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
        verify(signatures, "evaluation", signature, REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    artifact = ArtifactRequest.model_validate(
        {k: getattr(body, k) for k in ArtifactRequest.model_fields}
    )
    permit = None
    try:
        permit = request.app.state.artifact_permit_access.check(artifact)
    except HTTPException as exc:
        if exc.status_code != 409:
            raise
    try:
        with Session(request.app.state.engine) as session, session.begin():
            now = datetime.now(UTC)
            session.execute(delete(MediaNonce).where(MediaNonce.expires_at < now))
            session.add(MediaNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            subject = lock(session, MediaSubject, body.candidate_id, allow_blocked=True)
            row = matches(session, body, "media")
            output = {}
            if permit and not subject.blocked and row:
                request.app.state.processing_access.check(body.candidate_id)
                request.app.state.recording_access.check_recording(
                    body.candidate_id, UUID(row.consent_id)
                )
                assembled(session, row)
                chunk = session.get(RecordingChunk, (row.id, body.number))
                if chunk:
                    output = {
                        "data_base64": base64.b64encode(chunk_bytes(session, row, chunk)).decode(),
                        "chunk_digest": chunk.digest,
                        "total_size": row.size,
                    }
            if output:
                request.app.state.processing_access.check(body.candidate_id)
                request.app.state.recording_access.check_recording(
                    body.candidate_id, UUID(row.consent_id)
                )
                permit = request.app.state.artifact_permit_access.check(artifact)
            if permit and not fresh(permit.issued_at):
                raise HTTPException(503)
            reply = PlaybackReply(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=bool(output),
                **output,
            )
            raw, signed = canonical(reply), sign(signatures, RESPONSE, reply)
        return Response(
            content=raw,
            media_type="application/json",
            headers={"X-HR-Signature": signed, "Cache-Control": "no-store"},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc


@router.get("/stages/{stage_id}/recording/chunks/{number}")
def reviewer_chunk(request: Request, actor: Actor, stage_id: UUID, number: int):

    from reverse_hr.domains.evaluation_review import authorize, guarded

    candidate, version = authorize(request, actor, stage_id)
    with Session(request.app.state.engine) as session, session.begin():
        row = guarded(request, actor, stage_id, candidate, version, session)
        if row.material["task"]["format"] not in {"voice", "vcv"} or not 0 <= number <= 127:
            raise HTTPException(409)
        body = PlaybackRequest(
            **{
                k: UUID(getattr(row, k))
                for k in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
            },
            format=row.material["task"]["format"],
            snapshot_version=row.material["snapshot_version"],
            digest=row.material["snapshot_digest"],
            requester="evaluation",
            purpose="rubric-evidence",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
            number=number,
        )
    reply = request.app.state.playback_access.fetch(body)
    return Response(
        content=base64.b64decode(reply.data_base64, validate=True),
        media_type="application/octet-stream",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "X-Recording-Size": str(reply.total_size),
            "Content-Disposition": "attachment; filename=recording-part",
        },
    )
