"""Own code/SQL and permitted private blobs, with real File/S3 adapters."""

import base64
import hashlib
from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from test_media_security import S3

from reverse_hr.rights_export import records


def test_code_sql_snapshots_and_run_parent_ownership(service):
    from reverse_hr.domains.coding_workspace import RunRequest, Snapshot, Workspace

    target = service("coding-workspace")
    subject, other = uuid4(), uuid4()
    with Session(target.app.state.engine) as session, session.begin():
        for candidate, format, text in [
            (subject, "code", 'print("my code")'),
            (subject, "sql", "SELECT 1"),
            (other, "code", "private other solution"),
        ]:
            workspace, snapshot, run = map(str, (uuid4(), uuid4(), uuid4()))
            session.add(
                Workspace(
                    workspace_id=workspace,
                    candidate_id=str(candidate),
                    session_id=str(uuid4()),
                    stage_id=str(uuid4()),
                    format=format,
                    version=1,
                )
            )
            session.flush()
            session.add(
                Snapshot(
                    snapshot_id=snapshot,
                    workspace_id=workspace,
                    version=1,
                    files=[
                        {"path": "answer.sql" if format == "sql" else "answer.py", "content": text}
                    ],
                    digest=hashlib.sha256(text.encode()).hexdigest(),
                    created_at=datetime.now(UTC),
                )
            )
            session.flush()
            session.add(
                RunRequest(
                    run_id=run,
                    snapshot_id=snapshot,
                    status="executed",
                    runner_version=1,
                    created_at=datetime.now(UTC),
                )
            )
    with Session(target.app.state.engine) as session:
        values = list(records(session, "coding-workspace", subject))
    snapshots = [
        row["data"]["files"][0]["content"]
        for row in values
        if row["table"] == "workspace_snapshots"
    ]
    assert sorted(snapshots) == ["SELECT 1", 'print("my code")']
    assert len([row for row in values if row["table"] == "workspace_runs"]) == 2
    assert "private other solution" not in str(values)


@pytest.mark.parametrize("backend", ["file", "s3"])
def test_private_recording_bytes_export_without_paths(service, backend):
    from reverse_hr.domains.media import MediaStorageIdentity, Recording, RecordingChunk
    from reverse_hr.media_storage import object_key, store
    from reverse_hr.s3_storage import S3BlobStore

    target = service("media")
    subject, recording = uuid4(), uuid4()
    raw = b"private candidate media bytes" * 4000
    hashed = hashlib.sha256(raw).hexdigest()
    key = object_key(subject, recording, 0, hashed)
    if backend == "s3":
        target.app.state.engine.media_store = S3BlobStore(S3(), "test-private", "media/")
    with Session(target.app.state.engine) as session, session.begin():
        storage = target.app.state.engine.media_store
        identity = session.get(MediaStorageIdentity, "primary")
        if identity:
            identity.identity = storage.identity
        else:
            session.add(MediaStorageIdentity(name="primary", identity=storage.identity))
        storage.put(key, raw, hashed)
        session.add(
            Recording(
                id=str(recording),
                candidate_id=str(subject),
                session_id=str(uuid4()),
                stage_id=str(uuid4()),
                format="audio",
                consent_id=str(uuid4()),
                mime="audio/webm",
                size=len(raw),
                expected_digest=hashed,
                client_duration_ms=1000,
                version=1,
                status="recording",
                created_at=datetime.now(UTC),
                finalized_at=None,
                snapshot_id=None,
                validation=None,
            )
        )
        session.flush()
        session.add(
            RecordingChunk(
                recording_id=str(recording),
                number=0,
                digest=hashed,
                data=None,
                object_key=key,
                byte_size=len(raw),
                received_at=datetime.now(UTC),
            )
        )
    with Session(target.app.state.engine) as session:
        values = list(records(session, "media", subject))
        assert store(session).identity == storage.identity
    chunks = [
        base64.b64decode(row["data"]["base64"])
        for row in values
        if row["table"] == "recording_source"
    ]
    assert b"".join(chunks) == raw
    assert all(len(chunk) <= 32768 for chunk in chunks)
    assert key not in str(values)
    with Session(target.app.state.engine) as session:
        assert list(records(session, "media", uuid4())) == []


def test_original_resume_pdf_chunked_with_integrity_and_ownership(service, tmp_path):
    from reverse_hr.domains.candidate_resume import ResumeImport, configure, storage
    from reverse_hr.media_storage import object_key

    target = service("candidate")
    configure(
        target.app.state.engine,
        SimpleNamespace(
            resume_storage_root=str(tmp_path / "private-pdf"), resume_antivirus_required=False
        ),
    )
    subject, import_id = uuid4(), uuid4()
    # Export does not execute, parse or render the user's original binary.
    raw = b"%PDF-1.7\n" + b"private original PDF bytes" * 4000
    hashed = hashlib.sha256(raw).hexdigest()
    key = object_key(subject, import_id, 0, hashed)
    with Session(target.app.state.engine) as session, session.begin():
        storage(session).put(key, raw, hashed)
        session.add(
            ResumeImport(
                import_id=str(import_id),
                candidate_id=str(subject),
                digest=hashed,
                size=len(raw),
                manifest=[{"key": key, "digest": hashed, "size": len(raw)}],
                status="pending",
                version=1,
                attempts=0,
                next_at=datetime.now(UTC),
                error=None,
                extraction=None,
                proposal=None,
            )
        )
    with Session(target.app.state.engine) as session:
        values = list(records(session, "candidate", subject))
    chunks = [
        base64.b64decode(row["data"]["base64"])
        for row in values
        if row["table"] == "resume_source_pdf"
    ]
    assert b"".join(chunks) == raw
    assert all(len(chunk) <= 32768 for chunk in chunks)
    assert key not in str(values)
