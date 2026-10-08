"""Private blobs, erasure acknowledgement, legacy rows and real FFmpeg decode."""

import hashlib
import os
import shutil
import subprocess
import sys
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_event_transport import signatures as signatures_fixture
from test_practical_environments import environment as environment_fixture
from test_practical_environments import prepared

from reverse_hr.db import Outbox
from reverse_hr.domains.media import Recording, RecordingChunk, assembled, process_deletion_request
from reverse_hr.events import EventEnvelope
from reverse_hr.media_storage import BlobUnavailable, FileBlobStore, object_key
from reverse_hr.media_validation import FFmpegValidator, command
from reverse_hr.settings import Settings

signatures = signatures_fixture


def reference(raw=b"private content"):
    return object_key(uuid4(), uuid4(), 0, hashlib.sha256(raw).hexdigest())


def test_blob_immutable_integrity_and_private_permissions(tmp_path):
    storage = FileBlobStore(tmp_path / "objects")
    raw = b"private content"
    digest = hashlib.sha256(raw).hexdigest()
    key = reference(raw)
    storage.put(key, raw, digest)
    storage.put(key, raw, digest)
    assert storage.read(key, len(raw), digest) == raw
    assert os.stat(storage.root / key).st_mode & 0o777 == 0o600
    assert os.stat(storage.root).st_mode & 0o777 == 0o700
    (storage.root / key).write_bytes(b"corrupted")
    with pytest.raises(BlobUnavailable):
        storage.read(key, len(raw), digest)
    with pytest.raises(BlobUnavailable):
        storage.put(key, raw, digest)
    assert not list(storage.root.rglob(".pending-*"))


@pytest.mark.parametrize("key", ["../outside", "/tmp/arbitrary", "a/../../b", "a" * 32 + "/x/y"])
def test_storage_rejects_arbitrary_keys(tmp_path, key):
    storage = FileBlobStore(tmp_path / "objects")
    with pytest.raises(BlobUnavailable):
        storage.put(key, b"x", hashlib.sha256(b"x").hexdigest())


def test_subject_erasure_removes_orphans_and_never_follows_symlinks(tmp_path):
    storage = FileBlobStore(tmp_path / "objects")
    subject, other, record = uuid4(), uuid4(), uuid4()
    digest = hashlib.sha256(b"x").hexdigest()
    key = object_key(subject, record, 0, digest)
    other_key = object_key(other, record, 0, digest)
    storage.put(key, b"x", digest)
    storage.put(other_key, b"x", digest)
    protected = tmp_path / "protected"
    protected.mkdir()
    (protected / "keep").write_text("keep")
    (storage.root / subject.hex / "link").symlink_to(protected, target_is_directory=True)
    storage.purge_subject(subject)
    storage.purge_subject(subject)
    assert not (storage.root / subject.hex).exists()
    assert storage.read(other_key, 1, digest) == b"x"
    assert (protected / "keep").read_text() == "keep"
    (storage.root / key.split("/")[0]).symlink_to(protected, target_is_directory=True)
    with pytest.raises(BlobUnavailable):
        storage.put(key, b"x", digest)
    assert list(protected.iterdir()) == [protected / "keep"]


def test_world_readable_storage_root_is_rejected(tmp_path):
    root = tmp_path / "objects"
    root.mkdir(mode=0o755)
    with pytest.raises(BlobUnavailable):
        FileBlobStore(root)


@pytest.fixture(params=["voice", "vcv"])
def media(request, service, token, signatures):
    return environment_fixture.__wrapped__(
        SimpleNamespace(param=("media", request.param)), service, token, signatures
    )


def test_new_upload_has_only_metadata_in_database_and_erasure_purges_blobs(media):
    s = media
    prepared(s)
    storage = s.env.app.state.engine.media_store
    with Session(s.env.app.state.engine) as db:
        parts = list(db.scalars(select(RecordingChunk)))
        assert parts and all(p.data is None and p.object_key and p.byte_size for p in parts)
    event = deletion(s.subject)
    with Session(s.env.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, event)
    assert not (storage.root / s.subject.hex).exists()


def deletion(subject):
    request = uuid4()
    return EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request},
    )


def test_storage_outage_never_acknowledges_erasure(media, monkeypatch):
    s = media
    prepared(s)
    storage = s.env.app.state.engine.media_store
    original = storage.purge_subject
    monkeypatch.setattr(
        storage, "purge_subject", lambda *_: (_ for _ in ()).throw(BlobUnavailable())
    )
    event = deletion(s.subject)
    with pytest.raises(BlobUnavailable), Session(s.env.app.state.engine) as db, db.begin():
        process_deletion_request(db, event)
    with Session(s.env.app.state.engine) as db:
        assert db.scalar(select(Recording)) is not None
        assert not any(
            row.envelope["event_type"] == "media.data_deleted.v1"
            for row in db.scalars(select(Outbox))
        )
    monkeypatch.setattr(storage, "purge_subject", original)
    with Session(s.env.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, event)
    assert not (storage.root / s.subject.hex).exists()


def test_legacy_database_parts_remain_readable(media):
    s = media
    ref, _ = prepared(s)
    with Session(s.env.app.state.engine) as db, db.begin():
        row = db.get(Recording, ref)
        raw = assembled(db, row)
        for part in db.scalars(select(RecordingChunk)):
            part.data = raw[part.number * 262144 : (part.number + 1) * 262144]
            part.object_key, part.byte_size = None, None
        row.validation = None
    reply = s.env.client.get(s.env_path + "/content", headers=s.auth)
    assert reply.status_code == 200 and reply.content == s.raw
    assert s.env.client.get(s.env_path, headers=s.auth).json()["validation"] is None


def test_corrupted_or_missing_private_blob_blocks_content(media):
    s = media
    prepared(s)
    with Session(s.env.app.state.engine) as db:
        part = db.get(RecordingChunk, (s.env_path.split("/")[-1], 0))
        path = s.env.app.state.engine.media_store.root / part.object_key
    path.write_bytes(b"corrupt")
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).status_code == 503
    path.unlink()
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).status_code == 503


@pytest.fixture(scope="module")
def recordings(tmp_path_factory):
    binary = shutil.which("ffmpeg")
    if not binary or not shutil.which("ffprobe"):
        pytest.skip("Real FFmpeg binaries unavailable")
    root = tmp_path_factory.mktemp("actual-media")
    samples = {}
    for mime, suffix, video, codecs in [
        ("audio/webm", "webm", False, ["-c:a", "libopus"]),
        ("audio/ogg", "ogg", False, ["-c:a", "libvorbis"]),
        ("video/webm", "webm", True, ["-c:a", "libopus", "-c:v", "libvpx"]),
        ("video/mp4", "mp4", True, ["-c:a", "aac", "-c:v", "libx264"]),
    ]:
        path = root / (mime.split("/")[0] + "." + suffix)
        args = [
            binary,
            "-nostdin",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=440:sample_rate=48000",
        ]
        if video:
            args += ["-f", "lavfi", "-i", "color=c=blue:s=64x48:r=10"]
        args += ["-t", "1", *codecs, "-threads", "1", "-y", str(path)]
        subprocess.run(args, check=True, capture_output=True, timeout=10)
        samples[mime] = path.read_bytes()
    return samples


@pytest.mark.parametrize("mime", ["audio/webm", "audio/ogg", "video/webm", "video/mp4"])
def test_real_full_decode_reports_server_duration(recordings, mime):
    report = FFmpegValidator(Settings()).validate(
        recordings[mime], mime, "voice" if mime.startswith("audio") else "vcv"
    )
    assert 900 <= report.duration_ms <= 1200
    assert report.sample_rate == 48000 and report.channels == 1
    assert (report.width, report.height) == ((64, 48) if mime.startswith("video") else (None, None))


@pytest.mark.parametrize(
    "raw,mime,format",
    [
        (b"\x1aE\xdf\xa3forged", "audio/webm", "voice"),
        (b"OggSforged", "audio/ogg", "voice"),
        (b"\0\0\0\x10ftypisomforged", "video/mp4", "vcv"),
        (b"#EXTM3U\nhttps://example.invalid/a.ts", "video/mp4", "vcv"),
    ],
)
def test_forged_container_and_playlist_are_rejected(recordings, raw, mime, format):
    with pytest.raises(HTTPException) as exc:
        FFmpegValidator(Settings()).validate(raw, mime, format)
    assert exc.value.status_code == 422


def test_mislabeled_streams_are_rejected(recordings):
    validator = FFmpegValidator(Settings())
    with pytest.raises(HTTPException) as exc:
        validator.validate(recordings["audio/webm"], "video/webm", "vcv")
    assert exc.value.status_code == 422
    with pytest.raises(HTTPException) as exc:
        validator.validate(recordings["video/webm"], "audio/webm", "voice")
    assert exc.value.status_code == 422


def test_decoder_timeout_and_output_limit():
    start = time_monotonic()
    with pytest.raises(HTTPException) as exc:
        command([sys.executable, "-c", "import time; time.sleep(5)"], 0.05)
    assert exc.value.status_code == 503 and time_monotonic() - start < 2
    with pytest.raises(HTTPException) as exc:
        command([sys.executable, "-c", "print('x' * 10000)"], 1, limit=100)
    assert exc.value.status_code == 422


def time_monotonic():
    import time

    return time.monotonic()


def test_missing_decoder_fails_closed():
    validator = FFmpegValidator(Settings(media_ffprobe_binary="/nonexistent/ffprobe"))
    with pytest.raises(HTTPException) as exc:
        validator.validate(b"x", "audio/webm", "voice")
    assert exc.value.status_code == 503


def test_real_decode_is_required_by_finalize_and_persisted(media, recordings):
    s = media
    mime = "audio/webm" if s.format == "voice" else "video/webm"
    s.raw = recordings[mime]
    s.env.app.state.media_validator = FFmpegValidator(s.env.app.state.settings)
    _, row = prepared(s)
    assert row["validation"]["validator"] == "ffmpeg-full-decode-v1"
    assert 900 <= row["validation"]["duration_ms"] <= 1200
    assert row["timestamps_trusted"] is False
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).content == s.raw


def test_failed_decode_does_not_finalize_or_queue_transcription(media):
    import base64

    from test_practical_environments import create

    from reverse_hr.media_transcription import TranscriptionAttempt

    s = media
    s.env.app.state.media_validator = FFmpegValidator(s.env.app.state.settings)
    s.raw = b"\x1aE\xdf\xa3forged-container"
    response = create(s)
    row = response.json()
    path = f"/v1/recordings/{row['recording_id']}"
    body = {
        "data_base64": base64.b64encode(s.raw).decode(),
        "digest": hashlib.sha256(s.raw).hexdigest(),
    }
    uploaded = s.env.client.put(path + "/chunks/0", headers=headers(s.auth, "upload", 1), json=body)
    assert uploaded.status_code == 200
    reply = s.env.client.post(path + "/finalize", headers=headers(s.auth, "finalize", 2))
    assert reply.status_code == 422
    current = s.env.client.get(path, headers=s.auth).json()
    assert current["status"] == "uploading" and current["version"] == 2
    assert current["snapshot_id"] is None and current["validation"] is None
    with Session(s.env.app.state.engine) as db:
        assert db.scalar(select(TranscriptionAttempt)) is None


def test_unconfigured_storage_does_not_accept_upload(media):
    import base64

    from test_practical_environments import create

    s = media
    s.raw = b"\x1aE\xdf\xa3upload"
    row = create(s).json()
    s.env.app.state.engine.media_store = None
    reply = s.env.client.put(
        f"/v1/recordings/{row['recording_id']}/chunks/0",
        headers=headers(s.auth, "upload", 1),
        json={
            "data_base64": base64.b64encode(s.raw).decode(),
            "digest": hashlib.sha256(s.raw).hexdigest(),
        },
    )
    assert reply.status_code == 503
    with Session(s.env.app.state.engine) as db:
        assert db.scalar(select(RecordingChunk)) is None


def test_decoder_busy_fails_without_starting_another_process(recordings):
    from reverse_hr.media_validation import _DECODER_SLOT

    assert _DECODER_SLOT.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as exc:
            FFmpegValidator(Settings()).validate(recordings["audio/webm"], "audio/webm", "voice")
        assert exc.value.status_code == 503
    finally:
        _DECODER_SLOT.release()


def test_wrong_storage_volume_cannot_read_or_acknowledge_erasure(media, tmp_path):
    s = media
    prepared(s)
    actual = s.env.app.state.engine.media_store
    s.env.app.state.engine.media_store = FileBlobStore(tmp_path / "wrong-volume")
    assert s.env.client.get(s.env_path + "/content", headers=s.auth).status_code == 503
    event = deletion(s.subject)
    with pytest.raises(HTTPException) as exc, Session(s.env.app.state.engine) as db, db.begin():
        process_deletion_request(db, event)
    assert exc.value.status_code == 503
    assert (actual.root / s.subject.hex).exists()
    with Session(s.env.app.state.engine) as db:
        assert not any(
            row.envelope["event_type"] == "media.data_deleted.v1"
            for row in db.scalars(select(Outbox))
        )
    s.env.app.state.engine.media_store = actual
    with Session(s.env.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, event)
    assert not (actual.root / s.subject.hex).exists()


def test_storage_upgrade_preserves_actual_legacy_bytes(tmp_path):
    from datetime import UTC, datetime

    from alembic import command as alembic_command
    from sqlalchemy import text

    from reverse_hr.db import make_engine
    from reverse_hr.migrate import migration_config

    settings = Settings(service_name="media", database_url=f"sqlite:///{tmp_path}/legacy.db")
    alembic_command.upgrade(migration_config(settings), "0003_media")
    engine = make_engine(settings.database_url.get_secret_value())
    raw, identifier = b"\x1aE\xdf\xa3legacy", str(uuid4())
    digest = hashlib.sha256(raw).hexdigest()
    with engine.begin() as connection:
        connection.execute(
            text("""INSERT INTO recordings
            (id,candidate_id,session_id,stage_id,format,consent_id,mime,size,expected_digest,
             client_duration_ms,version,status,created_at)
             VALUES (:id,:candidate,:session,:stage,'voice',:consent,'audio/webm',:size,:digest,
                     1000,2,'uploading',:created)"""),
            {
                "id": identifier,
                "candidate": str(uuid4()),
                "session": str(uuid4()),
                "stage": str(uuid4()),
                "consent": str(uuid4()),
                "size": len(raw),
                "digest": digest,
                "created": datetime.now(UTC),
            },
        )
        connection.execute(
            text("""INSERT INTO recording_chunks
            (recording_id,number,digest,data,received_at) VALUES (:id,0,:digest,:raw,:created)"""),
            {"id": identifier, "digest": digest, "raw": raw, "created": datetime.now(UTC)},
        )
    alembic_command.upgrade(migration_config(settings), "head")
    with Session(engine) as db:
        row = db.get(Recording, identifier)
        assert row.validation is None and assembled(db, row) == raw
        part = db.get(RecordingChunk, (identifier, 0))
        assert part.object_key is None and part.data == raw
    engine.dispose()


def test_transcript_cannot_claim_more_time_than_decoded_recording(media):
    from test_practical_environments import submit
    from test_practical_evaluation import Speech, transcribe

    from reverse_hr.media_transcription import Transcript, TranscriptionAttempt

    s = media
    ref, artifact = prepared(s)
    assert submit(s, ref, artifact).status_code == 200
    with Session(s.env.app.state.engine) as db, db.begin():
        row = db.get(Recording, ref)
        row.validation = row.validation | {"duration_ms": 1000}
    assert transcribe(s, Speech())
    with Session(s.env.app.state.engine) as db:
        assert db.get(Transcript, ref) is None
        assert db.scalar(select(TranscriptionAttempt)).status == "technical_failure"


def test_restart_after_invalid_decode_replaces_only_unfinalized_bytes(media, recordings):
    import base64

    from test_practical_environments import create

    s = media
    s.raw = b"\x1aE\xdf\xa3forged"
    s.env.app.state.media_validator = FFmpegValidator(s.env.app.state.settings)
    row = create(s).json()
    path = f"/v1/recordings/{row['recording_id']}"
    body = {
        "data_base64": base64.b64encode(s.raw).decode(),
        "digest": hashlib.sha256(s.raw).hexdigest(),
    }
    assert (
        s.env.client.put(
            path + "/chunks/0", headers=headers(s.auth, "old-part", 1), json=body
        ).status_code
        == 200
    )
    assert (
        s.env.client.post(path + "/finalize", headers=headers(s.auth, "bad", 2)).status_code == 422
    )
    with Session(s.env.app.state.engine) as db:
        old = db.get(RecordingChunk, (row["recording_id"], 0))
        old_path = s.env.app.state.engine.media_store.root / old.object_key
    mime = "audio/webm" if s.format == "voice" else "video/webm"
    raw = recordings[mime]
    manifest = {
        "session_id": s.session_id,
        "stage_id": s.stage_id,
        "recording_consent_id": s.recording_consent,
        "mime": mime,
        "size": len(raw),
        "digest": hashlib.sha256(raw).hexdigest(),
        "client_duration_ms": 7200000,
    }
    assert (
        s.env.client.post(
            path + "/restart", headers=headers(s.auth, "stale", 1), json=manifest
        ).status_code
        == 409
    )
    assert old_path.exists()
    reply = s.env.client.post(
        path + "/restart", headers=headers(s.auth, "restart", 2), json=manifest
    )
    assert reply.status_code == 200 and reply.json()["version"] == 3
    assert reply.json()["received_chunks"] == [] and not old_path.exists()
    repeated = s.env.client.post(
        path + "/restart", headers=headers(s.auth, "restart", 2), json=manifest
    )
    assert repeated.status_code == 200 and repeated.json()["version"] == 3
    chunk = {"data_base64": base64.b64encode(raw).decode(), "digest": manifest["digest"]}
    assert (
        s.env.client.put(
            path + "/chunks/0", headers=headers(s.auth, "new-part", 3), json=chunk
        ).status_code
        == 200
    )
    finalized = s.env.client.post(path + "/finalize", headers=headers(s.auth, "good", 4))
    assert finalized.status_code == 200
    assert finalized.json()["client_duration_ms"] == 7200000
    assert 900 <= finalized.json()["validation"]["duration_ms"] <= 1200
    assert (
        s.env.client.post(
            path + "/restart", headers=headers(s.auth, "too-late", 5), json=manifest
        ).status_code
        == 409
    )
    assert s.env.client.get(path + "/content", headers=s.auth).content == raw


def test_revocation_during_decode_prevents_snapshot_publication(media):
    import base64
    from types import SimpleNamespace

    from test_practical_environments import create

    from reverse_hr.domains.privacy import ConsentRecord
    from reverse_hr.media_transcription import TranscriptionAttempt

    s = media
    s.raw = b"\x1aE\xdf\xa3synthetic"
    delegate = s.env.app.state.media_validator

    def revoke(*args):
        report = delegate.validate(*args)
        with Session(s.privacy.app.state.engine) as db, db.begin():
            consent = db.get(ConsentRecord, s.recording_consent)
            consent.status = "revoked"
        return report

    s.env.app.state.media_validator = SimpleNamespace(validate=revoke)
    row = create(s).json()
    path = f"/v1/recordings/{row['recording_id']}"
    body = {
        "data_base64": base64.b64encode(s.raw).decode(),
        "digest": hashlib.sha256(s.raw).hexdigest(),
    }
    assert (
        s.env.client.put(
            path + "/chunks/0", headers=headers(s.auth, "part", 1), json=body
        ).status_code
        == 200
    )
    assert (
        s.env.client.post(path + "/finalize", headers=headers(s.auth, "seal", 2)).status_code == 409
    )
    with Session(s.env.app.state.engine) as db:
        current = db.get(Recording, row["recording_id"])
        assert current.status == "uploading" and current.version == 2
        assert current.snapshot_id is None and current.validation is None
        assert db.scalar(select(TranscriptionAttempt)) is None
