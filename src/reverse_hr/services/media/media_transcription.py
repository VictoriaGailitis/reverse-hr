"""Durable opt-in transcription attempts; ambiguous calls are never automatically replayed."""

import base64
import json
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, Protocol
from urllib.request import ProxyHandler, build_opener
from urllib.request import Request as HttpRequest
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.practical_evidence import TranscriptDocument, sha
from reverse_hr.protocols.market_state import lock
from reverse_hr.protocols.processing_access import NoRedirect
from reverse_hr.services.media.domain.media import (
    MediaBase,
    MediaSubject,
    Recording,
    assembled,
    guard,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, execute
from reverse_hr.shared.db import enqueue

_SLOT = threading.BoundedSemaphore(1)


class Transcript(MediaBase):
    __tablename__ = "media_transcripts"
    recording_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    transcript_id: Mapped[str] = mapped_column(String(36), unique=True)
    attempt_id: Mapped[str] = mapped_column(String(36), unique=True)
    recording_digest: Mapped[str] = mapped_column(String(64))
    digest: Mapped[str] = mapped_column(String(64))
    document: Mapped[dict] = mapped_column(JSON)
    model: Mapped[str] = mapped_column(String(200))


class TranscriptionAttempt(MediaBase):
    __tablename__ = "media_transcription_attempts"
    __table_args__ = (UniqueConstraint("recording_id", "number"),)
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    recording_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    number: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))
    recording_digest: Mapped[str] = mapped_column(String(64))
    model: Mapped[str | None] = mapped_column(String(200))
    cost_microusd: Mapped[int | None]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TranscriptionView(Contract):
    attempt_id: UUID
    number: int
    status: Literal["pending", "running", "ready", "technical_failure", "interrupted", "blocked"]
    model: str | None
    cost_microusd: int | None
    transcript_id: UUID | None
    transcript_digest: str | None
    document: TranscriptDocument | None


class TranscriptionReply(Contract):
    recording_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    model: str = Field(min_length=1, max_length=200)
    document: TranscriptDocument
    cost_microusd: int = Field(strict=True, ge=0, le=2147483647)


class TranscriptionGateway(Protocol):
    model: str

    def transcribe(
        self, *, raw: bytes, mime: str, digest: str, timeout_seconds: int
    ) -> TranscriptionReply: ...


def event(session, row, kind, version):
    enqueue(
        session,
        EventEnvelope(
            producer="media",
            event_type=f"media.transcription_{kind}.v1",
            correlation_id=uuid4(),
            aggregate_id=UUID(row.attempt_id),
            aggregate_version=version,
            payload={
                "candidate_id": UUID(row.candidate_id),
                "recording_id": UUID(row.recording_id),
                "attempt_id": UUID(row.attempt_id),
            },
        ),
    )


def enqueue_attempt(session, row):
    previous = session.scalar(
        select(TranscriptionAttempt)
        .where(TranscriptionAttempt.recording_id == row.id)
        .order_by(TranscriptionAttempt.number.desc())
        .limit(1)
    )
    if previous and previous.status in {"pending", "running", "ready"}:
        return previous
    if previous and previous.number >= 3:
        raise HTTPException(409, "Transcription attempt limit reached")
    attempt = TranscriptionAttempt(
        attempt_id=str(uuid4()),
        recording_id=row.id,
        candidate_id=row.candidate_id,
        number=previous.number + 1 if previous else 1,
        status="pending",
        recording_digest=row.expected_digest,
        created_at=datetime.now(UTC),
    )
    session.add(attempt)
    event(session, attempt, "queued", 1)
    session.flush()
    return attempt


def view(session, attempt):
    transcript = session.get(Transcript, attempt.recording_id)
    return TranscriptionView(
        attempt_id=attempt.attempt_id,
        number=attempt.number,
        status=attempt.status,
        model=attempt.model,
        cost_microusd=attempt.cost_microusd,
        transcript_id=transcript.transcript_id if transcript else None,
        transcript_digest=transcript.digest if transcript else None,
        document=transcript.document if transcript else None,
    ).model_dump(mode="json")


router = APIRouter(prefix="/v1/recordings", tags=["media-transcription"])


@router.post("/{recording_id}/transcription", response_model=TranscriptionView, status_code=202)
def request_transcription(
    request: Request, actor: Actor, recording_id: UUID, idempotency: CommandKey
):
    def admit(session):
        row = guard(request, session, actor, recording_id)
        if row.status != "finalized":
            raise HTTPException(409)

    def change(session):
        attempt = enqueue_attempt(session, session.get(Recording, str(recording_id)))
        return {"attempt_id": attempt.attempt_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"request_transcription:{recording_id}",
        idempotency,
        {},
        change,
        202,
        guard=admit,
        present=lambda session, result: view(
            session, session.get(TranscriptionAttempt, result["attempt_id"])
        ),
    )


@router.get("/{recording_id}/transcription", response_model=TranscriptionView)
def get_transcription(request: Request, actor: Actor, recording_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        guard(request, session, actor, recording_id)
        attempt = session.scalar(
            select(TranscriptionAttempt)
            .where(TranscriptionAttempt.recording_id == str(recording_id))
            .order_by(TranscriptionAttempt.number.desc())
            .limit(1)
        )
        if attempt is None:
            raise HTTPException(404)
        return view(session, attempt)


@router.post(
    "/{recording_id}/transcription/{attempt_id}/interrupt", response_model=TranscriptionView
)
def interrupt(
    request: Request, actor: Actor, recording_id: UUID, attempt_id: UUID, idempotency: CommandKey
):
    def change(session):
        attempt = session.get(TranscriptionAttempt, str(attempt_id))
        if attempt is None or attempt.recording_id != str(recording_id):
            raise HTTPException(404)
        if attempt.status not in {"pending", "running"}:
            raise HTTPException(409)
        attempt.status = "interrupted"
        event(session, attempt, "interrupted", 2)
        return {"attempt_id": attempt.attempt_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"interrupt_transcription:{attempt_id}",
        idempotency,
        {},
        change,
        guard=lambda session: guard(request, session, actor, recording_id),
        present=lambda session, result: view(
            session, session.get(TranscriptionAttempt, result["attempt_id"])
        ),
    )


def admission(processing, recording, stages, row):
    processing.check(UUID(row.candidate_id))
    recording.check_recording(UUID(row.candidate_id), UUID(row.consent_id))
    if (
        stages.check_stage(UUID(row.candidate_id), UUID(row.session_id), UUID(row.stage_id), "read")
        != row.format
    ):
        raise HTTPException(409)


def run_one(engine, processing, recording, stages, gateway, *, timeout_seconds=30):
    if (
        gateway is None
        or not 1 <= timeout_seconds <= 30
        or not isinstance(gateway.model, str)
        or not 1 <= len(gateway.model) <= 200
    ):
        raise HTTPException(503)
    with Session(engine) as session:
        attempt = session.scalar(
            select(TranscriptionAttempt)
            .where(TranscriptionAttempt.status == "pending")
            .order_by(TranscriptionAttempt.created_at)
            .limit(1)
        )
        if attempt is None:
            return False
        ref, candidate = attempt.attempt_id, attempt.candidate_id
        row = session.get(Recording, attempt.recording_id)
        if row is None:
            raise HTTPException(409)
        denied = False
        try:
            admission(processing, recording, stages, row)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            denied = True
    if denied:
        with Session(engine) as session, session.begin():
            lock(session, MediaSubject, candidate, allow_blocked=True)
            attempt = session.get(TranscriptionAttempt, ref)
            if attempt is not None and attempt.status == "pending":
                attempt.status = "blocked"
                event(session, attempt, "blocked", 2)
        return True
    if not _SLOT.acquire(blocking=False):
        raise HTTPException(503)
    launch = False
    try:
        with Session(engine) as session, session.begin():
            subject = lock(session, MediaSubject, candidate, allow_blocked=True)
            attempt = session.scalar(
                select(TranscriptionAttempt)
                .where(TranscriptionAttempt.attempt_id == ref)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if attempt is None or attempt.status != "pending":
                return True
            row = session.get(Recording, attempt.recording_id)
            if (
                subject.blocked
                or row is None
                or row.status != "finalized"
                or row.expected_digest != attempt.recording_digest
            ):
                attempt.status = "blocked"
                event(session, attempt, "blocked", 2)
                return True
            admission(processing, recording, stages, row)
            raw, mime, expected = assembled(session, row), row.mime, row.expected_digest
            admission(processing, recording, stages, row)
            decoded_duration = row.validation["duration_ms"] if row.validation else None
            attempt.status, attempt.model = "running", gateway.model
            event(session, attempt, "started", 2)
        launch = True
    finally:
        if not launch:
            _SLOT.release()
    result, done = [], threading.Event()

    def call():
        try:
            reply = gateway.transcribe(
                raw=raw, mime=mime, digest=expected, timeout_seconds=timeout_seconds
            )
            reply = TranscriptionReply.model_validate(reply.model_dump(mode="json"))
            result.append(
                reply
                if reply.recording_digest == expected
                and reply.model == gateway.model
                and (
                    decoded_duration is None or reply.document.duration_ms <= decoded_duration + 250
                )
                else None
            )
        except Exception:
            result.append(None)
        finally:
            done.set()
            _SLOT.release()

    thread = threading.Thread(target=call, daemon=True)
    try:
        thread.start()
    except BaseException:
        _SLOT.release()
        raise
    finished = done.wait(timeout_seconds)
    with Session(engine) as session, session.begin():
        subject = lock(session, MediaSubject, candidate, allow_blocked=True)
        attempt = session.get(TranscriptionAttempt, ref)
        if subject.blocked or attempt is None or attempt.status != "running":
            return True
        row = session.get(Recording, attempt.recording_id)
        try:
            admission(processing, recording, stages, row)
        except HTTPException as exc:
            attempt.status = "blocked" if exc.status_code == 409 else "technical_failure"
            event(session, attempt, "blocked" if exc.status_code == 409 else "failed", 3)
            return True
        reply = result[0] if finished and result else None
        attempt.status = "ready" if reply else "technical_failure"
        if reply:
            session.add(
                Transcript(
                    recording_id=row.id,
                    transcript_id=str(uuid4()),
                    attempt_id=ref,
                    recording_digest=expected,
                    digest=sha(reply.document),
                    document=reply.document.model_dump(mode="json"),
                    model=reply.model,
                )
            )
            attempt.cost_microusd = reply.cost_microusd
        event(session, attempt, "ready" if reply else "failed", 3)
    return True


class HttpTranscriptionGateway:
    """Operator-owned HTTP gateway contract; no vendor-specific API or automatic retry."""

    def __init__(self, settings):
        if (
            not settings.media_transcription_enabled
            or not settings.media_transcription_origin
            or not settings.media_transcription_model
            or not settings.media_transcription_key_file
        ):
            raise ValueError("Transcription gateway unavailable")
        settings.validate_origin(settings.media_transcription_origin)
        if not settings.media_transcription_origin.startswith("https://"):
            raise ValueError("Transcription gateway requires HTTPS")
        self.origin, self.model = (
            settings.media_transcription_origin,
            settings.media_transcription_model,
        )
        with Path(settings.media_transcription_key_file).open("rb") as stream:
            raw = stream.read(4097)
        self.key = raw.decode("ascii").strip()
        if len(raw) > 4096 or not self.key or any(ord(c) <= 32 or ord(c) >= 127 for c in self.key):
            raise ValueError("Invalid transcription credential file")
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def transcribe(self, *, raw, mime, digest, timeout_seconds):
        if not 1 <= len(raw) <= 32 * 1024 * 1024 or not 1 <= timeout_seconds <= 30:
            raise ValueError("Invalid transcription request")
        wire = json.dumps(
            {
                "model": self.model,
                "recording_digest": digest,
                "mime": mime,
                "data_base64": base64.b64encode(raw).decode(),
                "store": False,
            },
            separators=(",", ":"),
        ).encode()
        request = HttpRequest(
            self.origin.rstrip("/") + "/v1/transcribe",
            data=wire,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.key,
                "Accept-Encoding": "identity",
            },
        )
        with self.opener.open(request, timeout=timeout_seconds) as response:
            if (
                response.status != 200
                or response.headers.get("Content-Encoding", "identity") != "identity"
            ):
                raise ValueError("Unavailable transcription response")
            body = response.read(262145)
        if len(body) > 262144:
            raise ValueError("Oversized transcription response")
        from reverse_hr.shared.llm_json import json_object

        return TranscriptionReply.model_validate(json_object(body))
