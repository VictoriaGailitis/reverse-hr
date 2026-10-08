"""Private resumable recording uploads; client timestamps are untrusted metadata."""

import base64
import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    LargeBinary,
    String,
    UniqueConstraint,
    delete,
    select,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.market_cleanup import erase
from reverse_hr.market_state import lock
from reverse_hr.media_storage import BlobUnavailable, object_key, store
from reverse_hr.media_validation import MediaValidation
from reverse_hr.practical_common import emit, owned, receipt
from reverse_hr.snapshot_access import SnapshotReceipt, SnapshotRequest

CHUNK_BYTES = 262144
MAX_BYTES = 32 * 1024 * 1024


class MediaBase(DeclarativeBase):
    pass


class MediaSubject(MediaBase):
    __tablename__ = "media_subjects"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)


class MediaStorageIdentity(MediaBase):
    __tablename__ = "media_storage_identity"
    name: Mapped[str] = mapped_column(String(16), primary_key=True)
    identity: Mapped[str] = mapped_column(String(36))


class Recording(MediaBase):
    __tablename__ = "recordings"
    __table_args__ = (UniqueConstraint("candidate_id", "session_id", "stage_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    stage_id: Mapped[str] = mapped_column(String(36))
    format: Mapped[str] = mapped_column(String(16))
    consent_id: Mapped[str] = mapped_column(String(36))
    mime: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    expected_digest: Mapped[str] = mapped_column(String(64))
    client_duration_ms: Mapped[int]
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finalized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    snapshot_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    validation: Mapped[dict | None] = mapped_column(JSON)


class RecordingChunk(MediaBase):
    __tablename__ = "recording_chunks"
    recording_id: Mapped[str] = mapped_column(ForeignKey("recordings.id"), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    digest: Mapped[str] = mapped_column(String(64))
    data: Mapped[bytes | None] = mapped_column(LargeBinary)
    object_key: Mapped[str | None] = mapped_column(String(134))
    byte_size: Mapped[int | None]
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class MediaNonce(MediaBase):
    __tablename__ = "media_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RecordingAdmission(Contract):
    session_id: UUID
    stage_id: UUID
    recording_consent_id: UUID


class RecordingCreate(RecordingAdmission):
    mime: Literal["audio/webm", "video/webm", "audio/ogg", "video/mp4"]
    size: int = Field(strict=True, ge=1, le=MAX_BYTES)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    client_duration_ms: int = Field(strict=True, ge=1, le=7200000)


class ChunkCommand(Contract):
    data_base64: str = Field(min_length=4, max_length=349528)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def valid_data(self):
        try:
            raw = base64.b64decode(self.data_base64, validate=True)
        except ValueError as exc:
            raise ValueError("Invalid chunk encoding") from exc
        if (
            not 1 <= len(raw) <= CHUNK_BYTES
            or base64.b64encode(raw).decode() != self.data_base64
            or hashlib.sha256(raw).hexdigest() != self.digest
        ):
            raise ValueError("Invalid chunk integrity")
        return self


class RecordingView(Contract):
    recording_id: UUID
    session_id: UUID
    stage_id: UUID
    format: Literal["voice", "vcv"]
    mime: str
    size: int
    digest: str
    chunk_bytes: int = CHUNK_BYTES
    received_chunks: list[int]
    status: Literal["uploading", "finalized"]
    version: int
    snapshot_id: UUID | None
    client_duration_ms: int
    validation: MediaValidation | None = None
    timestamps_trusted: Literal[False] = False
    created_at: datetime
    finalized_at: datetime | None
    demo: Literal[True] = True


router = APIRouter(prefix="/v1/recordings", tags=["media"])
internal_router = APIRouter(prefix="/internal/v1", tags=["internal-media"])


@router.post("/admission")
def recording_admission(request: Request, actor: Actor, body: RecordingAdmission):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, MediaSubject, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        request.app.state.recording_access.check_recording(actor.subject, body.recording_consent_id)
        format = request.app.state.stage_access.check_stage(
            actor.subject, body.session_id, body.stage_id
        )
        if format not in {"voice", "vcv"}:
            raise HTTPException(409)
        return {"format": format, "max_bytes": MAX_BYTES, "allowed": True}


def guard(request, session, actor, ref, purpose="read"):
    return owned(request, session, actor, Recording, MediaSubject, ref, purpose=purpose)


def view(session, row):
    session.flush()
    return RecordingView(
        recording_id=row.id,
        session_id=row.session_id,
        stage_id=row.stage_id,
        format=row.format,
        mime=row.mime,
        size=row.size,
        digest=row.expected_digest,
        received_chunks=list(
            session.scalars(
                select(RecordingChunk.number)
                .where(RecordingChunk.recording_id == row.id)
                .order_by(RecordingChunk.number)
            )
        ),
        status=row.status,
        version=row.version,
        snapshot_id=row.snapshot_id,
        client_duration_ms=row.client_duration_ms,
        validation=row.validation,
        created_at=row.created_at.replace(tzinfo=UTC)
        if row.created_at.tzinfo is None
        else row.created_at,
        finalized_at=(
            row.finalized_at.replace(tzinfo=UTC)
            if row.finalized_at and row.finalized_at.tzinfo is None
            else row.finalized_at
        ),
    ).model_dump(mode="json")


@router.post("", response_model=RecordingView, status_code=201)
def create(request: Request, actor: Actor, body: RecordingCreate, idempotency: CommandKey):
    actor.require("candidate")
    format = None

    def admit(session):
        nonlocal format
        lock(session, MediaSubject, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        request.app.state.recording_access.check_recording(actor.subject, body.recording_consent_id)
        format = request.app.state.stage_access.check_stage(
            actor.subject, body.session_id, body.stage_id
        )
        if (
            format not in {"voice", "vcv"}
            or (format == "voice" and not body.mime.startswith("audio/"))
            or (format == "vcv" and not body.mime.startswith("video/"))
        ):
            raise HTTPException(409)

    def change(session):
        row = Recording(
            id=str(uuid4()),
            candidate_id=str(actor.subject),
            session_id=str(body.session_id),
            stage_id=str(body.stage_id),
            format=format,
            consent_id=str(body.recording_consent_id),
            mime=body.mime,
            size=body.size,
            expected_digest=body.digest,
            client_duration_ms=body.client_duration_ms,
            version=1,
            status="uploading",
            created_at=datetime.now(UTC),
        )
        session.add(row)
        emit(session, request, row, "recording_created")
        return {"id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "recording_create",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=admit,
        present=lambda session, result: view(session, guard(request, session, actor, result["id"])),
    )


@router.get("/{recording_id}", response_model=RecordingView)
def get_recording(request: Request, actor: Actor, recording_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        return view(session, guard(request, session, actor, recording_id))


@router.put("/{recording_id}/chunks/{number}", response_model=RecordingView)
def upload(
    request: Request,
    actor: Actor,
    recording_id: UUID,
    number: int,
    body: ChunkCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    raw = base64.b64decode(body.data_base64, validate=True)

    def change(session):
        row = session.get(Recording, str(recording_id))
        if (
            row.status != "uploading"
            or not 0 <= number < (row.size + CHUNK_BYTES - 1) // CHUNK_BYTES
        ):
            raise HTTPException(409)
        expected_size = min(CHUNK_BYTES, row.size - number * CHUNK_BYTES)
        if len(raw) != expected_size:
            raise HTTPException(422)
        previous = session.get(RecordingChunk, (row.id, number))
        if previous:
            if previous.digest != body.digest or chunk_bytes(session, row, previous) != raw:
                raise HTTPException(409)
            return {"id": row.id}
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        storage = store(session, bind=True)
        if storage is None:
            raise HTTPException(503, "Private media storage is not configured")
        key = object_key(row.candidate_id, row.id, number, body.digest)
        try:
            storage.put(key, raw, body.digest)
        except BlobUnavailable as exc:
            raise HTTPException(503, "Private media storage unavailable") from exc
        session.add(
            RecordingChunk(
                recording_id=row.id,
                number=number,
                digest=body.digest,
                data=None,
                object_key=key,
                byte_size=len(raw),
                received_at=datetime.now(UTC),
            )
        )
        row.version += 1
        return {"id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"recording_chunk:{recording_id}:{number}",
        idempotency,
        {"digest": body.digest, "version": if_match},
        change,
        guard=lambda session: guard(request, session, actor, recording_id, "write"),
        present=lambda session, result: view(session, session.get(Recording, result["id"])),
    )


def chunk_bytes(session, row, part):
    if row.status == "finalized" and getattr(session.get_bind(), "media_antivirus_required", False):
        report = MediaValidation.model_validate(row.validation) if row.validation else None
        if not report or not report.antivirus or report.antivirus.digest != row.expected_digest:
            raise HTTPException(503, "Recording requires antivirus revalidation")
    if part.object_key is None:
        raw = part.data
        if raw is None or not 1 <= len(raw) <= CHUNK_BYTES:
            raise HTTPException(409)
    else:
        if part.data is not None or part.object_key != object_key(
            row.candidate_id, row.id, part.number, part.digest
        ):
            raise HTTPException(409)
        storage = store(session)
        if storage is None:
            raise HTTPException(503, "Private media storage is not configured")
        try:
            raw = storage.read(part.object_key, part.byte_size, part.digest)
        except BlobUnavailable as exc:
            raise HTTPException(503, "Private media blob unavailable") from exc
    if hashlib.sha256(raw).hexdigest() != part.digest:
        raise HTTPException(409)
    return raw


@router.post("/{recording_id}/restart", response_model=RecordingView)
def restart(
    request: Request,
    actor: Actor,
    recording_id: UUID,
    body: RecordingCreate,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def admit(session):
        row = guard(request, session, actor, recording_id, "write")
        if (
            str(body.session_id) != row.session_id
            or str(body.stage_id) != row.stage_id
            or str(body.recording_consent_id) != row.consent_id
            or (row.format == "voice" and not body.mime.startswith("audio/"))
            or (row.format == "vcv" and not body.mime.startswith("video/"))
        ):
            raise HTTPException(409)

    def change(session):
        row = session.get(Recording, str(recording_id))
        if row.status != "uploading" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        storage = store(session)
        if storage is None:
            raise HTTPException(503, "Private media storage is not configured")
        try:
            storage.purge_recording(row.candidate_id, row.id)
        except BlobUnavailable as exc:
            raise HTTPException(503, "Private media reset unavailable") from exc
        session.execute(delete(RecordingChunk).where(RecordingChunk.recording_id == row.id))
        row.mime, row.size, row.expected_digest = body.mime, body.size, body.digest
        row.client_duration_ms = body.client_duration_ms
        row.version += 1
        emit(session, request, row, "recording_restarted")
        return {"id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"recording_restart:{recording_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=admit,
        present=lambda session, result: view(session, session.get(Recording, result["id"])),
    )


def assembled(session, row):
    chunks = list(
        session.scalars(
            select(RecordingChunk)
            .where(RecordingChunk.recording_id == row.id)
            .order_by(RecordingChunk.number)
        )
    )
    if [part.number for part in chunks] != list(range((row.size + CHUNK_BYTES - 1) // CHUNK_BYTES)):
        raise HTTPException(409)
    raw = b"".join(chunk_bytes(session, row, part) for part in chunks)
    if len(raw) != row.size or hashlib.sha256(raw).hexdigest() != row.expected_digest:
        raise HTTPException(409)
    # Container signatures are a bounded structural check, not a decode/transcription verdict.
    valid = (
        raw.startswith(b"\x1aE\xdf\xa3")
        if row.mime.endswith("webm")
        else raw.startswith(b"OggS")
        if row.mime.endswith("ogg")
        else len(raw) >= 12 and raw[4:8] == b"ftyp"
    )
    if not valid:
        raise HTTPException(422)
    return raw


@router.post("/{recording_id}/finalize", response_model=RecordingView)
def finalize(
    request: Request,
    actor: Actor,
    recording_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(Recording, str(recording_id))
        if row.status != "uploading" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        raw = assembled(session, row)
        scanner = request.app.state.media_scanner
        scan = scanner.scan(raw) if scanner is not None else None
        if scan is not None:
            from reverse_hr.media_antivirus import AntivirusReport

            scan = AntivirusReport.model_validate(scan)
            if scan.digest != row.expected_digest:
                raise HTTPException(503, "Antivirus receipt does not match the upload")
            guard(request, session, actor, recording_id, "write")
        report = request.app.state.media_validator.validate(raw, row.mime, row.format)
        # Decode may take seconds: refresh consent, stage deadline and erasure admission.
        guard(request, session, actor, recording_id, "write")
        report = MediaValidation.model_validate(report)
        if scan is not None:
            report = report.model_copy(update={"antivirus": scan})
        row.validation = report.model_dump(mode="json")
        row.status = "finalized"
        row.version += 1
        row.snapshot_id = str(uuid4())
        row.finalized_at = datetime.now(UTC)
        emit(session, request, row, "recording_finalized")
        from reverse_hr.media_transcription import enqueue_attempt

        enqueue_attempt(session, row)
        return {"id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"recording_finalize:{recording_id}",
        idempotency,
        {"version": if_match},
        change,
        guard=lambda session: guard(request, session, actor, recording_id, "write"),
        present=lambda session, result: view(session, session.get(Recording, result["id"])),
    )


@router.get("/{recording_id}/content")
def content(request: Request, actor: Actor, recording_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = guard(request, session, actor, recording_id)
        if row.status != "finalized":
            raise HTTPException(409)
        raw = assembled(session, row)
        guard(request, session, actor, recording_id)
        return Response(
            content=raw,
            media_type=row.mime,
            headers={
                "Cache-Control": "no-store",
                "X-Content-Type-Options": "nosniff",
                "Content-Disposition": "attachment; filename=recording",
            },
        )


@internal_router.post("/practical-receipt", response_model=SnapshotReceipt)
def snapshot_receipt(
    request: Request,
    body: SnapshotRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    def resolve(session, body):
        row = session.get(Recording, str(body.workspace_id))
        if (
            row
            and row.status == "finalized"
            and row.snapshot_id == str(body.snapshot_id)
            and row.candidate_id == str(body.candidate_id)
            and row.session_id == str(body.session_id)
            and row.stage_id == str(body.stage_id)
        ):
            request.app.state.recording_access.check_recording(
                body.candidate_id, UUID(row.consent_id)
            )
            assembled(session, row)
            request.app.state.processing_access.check(body.candidate_id)
            request.app.state.recording_access.check_recording(
                body.candidate_id, UUID(row.consent_id)
            )
            return {
                "format": row.format,
                "snapshot_version": row.version,
                "digest": row.expected_digest,
            }

    return receipt(request, body, signature, MediaNonce, MediaSubject, resolve)


def process_deletion_request(session, event):
    def scrub(subject):
        ids = list(session.scalars(select(Recording.id).where(Recording.candidate_id == subject)))
        from reverse_hr.media_transcription import Transcript, TranscriptionAttempt

        storage = store(session)
        has_blobs = session.scalar(
            select(RecordingChunk.recording_id)
            .where(RecordingChunk.recording_id.in_(ids), RecordingChunk.object_key.is_not(None))
            .limit(1)
        )
        if has_blobs and storage is None:
            raise BlobUnavailable("Cannot acknowledge deletion without private storage")
        if storage is not None:
            # Purge before ACK; retries also remove writes orphaned by a rolled-back upload.
            storage.purge_subject(subject)

        session.execute(delete(Transcript).where(Transcript.recording_id.in_(ids)))
        session.execute(
            delete(TranscriptionAttempt).where(TranscriptionAttempt.recording_id.in_(ids))
        )
        session.execute(delete(RecordingChunk).where(RecordingChunk.recording_id.in_(ids)))
        session.execute(delete(Recording).where(Recording.id.in_(ids)))

    return erase(session, event, "media", MediaSubject, scrub)
