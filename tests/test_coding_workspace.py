from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_assessment_sessions import make_session, plan
from test_processing_access import signing as signing_fixture

from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.coding_workspace import (
    RunRequest,
    Snapshot,
    Workspace,
    WorkspaceSubject,
    process_deletion_request,
)
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import REQUEST_CONTEXT, canonical, sign
from reverse_hr.settings import Settings
from reverse_hr.stage_access import STAGE_REQUEST_CONTEXT, StageAccess, StageRequest


@pytest.fixture
def workspace_setup(service, token):
    signatures = signing_fixture.__wrapped__()
    assessment = service("assessment")
    assessment.app.state.assessment_signatures = signatures["assessment"]
    version, _, _ = plan(assessment, token)
    subject = uuid4()
    reply, auth, _ = make_session(assessment, token, version, subject)
    session = reply.json()
    workspace = service("coding-workspace")
    access = StageAccess(Settings(service_name="coding-workspace"))
    access._signatures = signatures["coding-workspace"]

    def send(body, signature):
        result = assessment.client.post(
            "/internal/v1/workspace-stage",
            content=body,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if result.status_code != 200:
            raise HTTPException(result.status_code)
        return result.content, result.headers["X-HR-Signature"]

    access.send_stage = send
    workspace.app.state.stage_access = access
    body = {
        "session_id": session["session_id"],
        "stage_id": session["stages"][0]["stage_id"],
        "files": [{"path": "main.py", "content": "print('synthetic')"}],
    }
    return workspace, assessment, auth, subject, body, signatures


def create(setup):
    workspace, _, auth, _, body, _ = setup
    reply = workspace.client.post("/v1/workspaces", headers=headers(auth), json=body)
    assert reply.status_code == 201, reply.text
    return reply.json()


def test_snapshots_conflicts_and_run_pins_original(workspace_setup, token):
    workspace, _, auth, _, body, _ = workspace_setup
    first = create(workspace_setup)
    path = f"/v1/workspaces/{first['workspace_id']}"
    assert workspace.client.post("/v1/workspaces", headers=headers(auth), json=body).json() == first
    assert (
        workspace.client.post(
            "/v1/workspaces", headers=headers(auth, "duplicate"), json=body
        ).status_code
        == 409
    )
    assert workspace.client.get(path, headers=token()).status_code == 404
    new_files = {"files": [{"path": "main.py", "content": "print('second')"}]}
    second = workspace.client.put(path + "/files", headers=headers(auth, "save", 1), json=new_files)
    assert second.status_code == 200
    assert second.json()["version"] == 2
    assert second.json()["digest"] != first["digest"]
    assert (
        workspace.client.put(
            path + "/files", headers=headers(auth, "stale", 1), json=new_files
        ).status_code
        == 409
    )
    assert (
        workspace.client.put(
            path + "/files", headers=headers(auth, "save", 1), json=new_files
        ).json()
        == second.json()
    )
    assert (
        workspace.client.get(path + "/snapshots/" + first["snapshot_id"], headers=auth).json()
        == first
    )
    assert workspace.client.get(path, headers=auth).json() == second.json()
    run = workspace.client.post(
        path + "/runs", headers=headers(auth, "run"), json={"snapshot_id": first["snapshot_id"]}
    )
    assert run.status_code == 202
    assert run.json()["status"] == "pending_runner"
    assert run.json()["snapshot_version"] == 1
    assert (
        workspace.client.post(
            path + "/runs", headers=headers(auth, "run"), json={"snapshot_id": first["snapshot_id"]}
        ).json()
        == run.json()
    )
    assert (
        workspace.client.get(path + "/runs/" + run.json()["run_id"], headers=auth).json()
        == run.json()
    )
    assert (
        workspace.client.post(
            path + "/runs", headers=headers(auth, "foreign"), json={"snapshot_id": str(uuid4())}
        ).status_code
        == 404
    )
    with Session(workspace.app.state.engine) as db:
        events = list(db.scalars(select(Outbox)))
        assert len(events) == 3
        assert "synthetic" not in str([event.envelope for event in events])
        assert len(list(db.scalars(select(Snapshot)))) == 2


@pytest.mark.parametrize(
    "files",
    [
        [{"path": "../main.py", "content": ""}],
        [{"path": "/tmp/main.py", "content": ""}],
        [{"path": "a//b.py", "content": ""}],
        [{"path": "a\\b.py", "content": ""}],
        [{"path": "main.py", "content": "я" * 40000}],
        [{"path": "main.py", "content": ""}, {"path": "main.py", "content": "x"}],
        [],
    ],
)
def test_reject_unsafe_or_oversized_files(workspace_setup, files):
    workspace, _, auth, _, body, _ = workspace_setup
    reply = workspace.client.post(
        "/v1/workspaces", headers=headers(auth), json=body | {"files": files}
    )
    assert reply.status_code == 422
    with Session(workspace.app.state.engine) as db:
        assert not list(db.scalars(select(Workspace)))
        assert not list(db.scalars(select(Outbox)))


def test_admission_cancel_consent_and_fail_closed(workspace_setup):
    workspace, assessment, auth, _, body, _ = workspace_setup
    first = create(workspace_setup)
    path = f"/v1/workspaces/{first['workspace_id']}"

    def withdrawn(*_):
        raise HTTPException(409)

    assessment.app.state.processing_access.check_assessment = withdrawn
    assert workspace.client.get(path, headers=auth).status_code == 409
    assert (
        workspace.client.post("/v1/workspaces", headers=headers(auth), json=body).status_code == 409
    )

    def unavailable(*_):
        raise HTTPException(503)

    assessment.app.state.processing_access.check_assessment = unavailable
    assert workspace.client.get(path, headers=auth).status_code == 503
    assessment.app.state.processing_access.check_assessment = lambda *_: None
    cancelled = assessment.client.post(
        f"/v1/assessment-sessions/{body['session_id']}/cancel", headers=headers(auth, "cancel", 1)
    )
    assert cancelled.status_code == 200
    assert workspace.client.get(path, headers=auth).status_code == 409


def test_stage_signature_binding_replay_and_wrong_owner(workspace_setup, token):
    workspace, assessment, auth, subject, body, signatures = workspace_setup

    def request(**changes):
        return StageRequest(
            candidate_id=subject,
            session_id=body["session_id"],
            stage_id=body["stage_id"],
            nonce=uuid4(),
            requester="coding-workspace",
            issued_at=datetime.now(UTC),
        ).model_copy(update=changes)

    def send(req, context=STAGE_REQUEST_CONTEXT):
        return assessment.client.post(
            "/internal/v1/workspace-stage",
            content=canonical(req),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": sign(signatures["coding-workspace"], context, req),
            },
        )

    req = request()
    assert send(req).json()["allowed"] is True
    assert send(req).status_code == 401
    assert send(request(), REQUEST_CONTEXT).status_code == 401
    assert send(request(issued_at=datetime.now(UTC) - timedelta(seconds=40))).status_code == 401
    assert send(request(candidate_id=uuid4())).json()["allowed"] is False
    assert send(request(stage_id=uuid4())).json()["allowed"] is False
    assert (
        workspace.client.post("/v1/workspaces", headers=headers(token()), json=body).status_code
        == 409
    )
    access = workspace.app.state.stage_access
    original = access.send_stage

    def tampered(raw, signature):
        data, sig = original(raw, signature)
        return data.replace(b'"format":"code"', b'"format":"sql"'), sig

    access.send_stage = tampered
    assert (
        workspace.client.post("/v1/workspaces", headers=headers(auth), json=body).status_code == 503
    )


def test_deletion_atomic_and_permanent(workspace_setup):
    workspace, _, auth, subject, body, _ = workspace_setup
    first = create(workspace_setup)
    path = f"/v1/workspaces/{first['workspace_id']}"
    assert (
        workspace.client.post(
            path + "/runs", headers=headers(auth, "run"), json={"snapshot_id": first["snapshot_id"]}
        ).status_code
        == 202
    )
    request_id = uuid4()
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    with Session(workspace.app.state.engine) as db:
        process_deletion_request(db, event)
        db.rollback()
    assert workspace.client.get(path, headers=auth).status_code == 200
    with Session(workspace.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, event)
    with Session(workspace.app.state.engine) as db, db.begin():
        assert not process_deletion_request(db, event)
        assert db.get(WorkspaceSubject, str(subject)).blocked
        for model in (Workspace, Snapshot, RunRequest, IdempotencyRecord):
            assert not list(db.scalars(select(model)))
        assert (
            len(
                [
                    e
                    for e in db.scalars(select(Outbox))
                    if e.envelope["event_type"] == "coding-workspace.data_deleted.v1"
                ]
            )
            == 1
        )
    assert (
        workspace.client.post("/v1/workspaces", headers=headers(auth), json=body).status_code == 409
    )


def test_signed_consumer_ack_after_commit(workspace_setup):
    from types import SimpleNamespace
    from unittest.mock import Mock

    from reverse_hr.event_transport import WorkspaceConsumer

    workspace, _, _, subject, _, signatures = workspace_setup
    first = create(workspace_setup)
    request_id = uuid4()
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    body, signed_headers = signatures["privacy"].sign(event)
    properties = SimpleNamespace(headers=signed_headers, message_id=str(event.event_id))
    channel = Mock()

    def ack(**_):
        with Session(workspace.app.state.engine) as db:
            assert db.get(Workspace, first["workspace_id"]) is None
            assert db.get(WorkspaceSubject, str(subject)).blocked
            assert [e.envelope["event_type"] for e in db.scalars(select(Outbox))] == [
                "coding-workspace.data_deleted.v1"
            ]

    channel.basic_ack.side_effect = ack
    consumer = WorkspaceConsumer(
        workspace.app.state.engine,
        signatures["coding-workspace"],
        Settings(service_name="coding-workspace"),
    )
    consumer(channel, SimpleNamespace(exchange="events.privacy", delivery_tag=1), properties, body)
    channel.basic_ack.assert_called_once_with(delivery_tag=1)
    channel.basic_publish.assert_not_called()


def test_workspace_migration_refuses_populated_downgrade(workspace_setup):
    from alembic import command

    from reverse_hr.migrate import migration_config

    workspace, _, _, _, _, _ = workspace_setup
    create(workspace_setup)
    with pytest.raises(RuntimeError, match="populated workspaces"):
        command.downgrade(migration_config(workspace.app.state.settings), "0001_transport")
    assert workspace.client.get("/health/ready").status_code == 200


def test_run_transaction_rolls_back_on_outbox_failure(workspace_setup, monkeypatch):
    import reverse_hr.domains.coding_workspace as domain

    workspace, _, auth, _, _, _ = workspace_setup
    first = create(workspace_setup)

    def fail(*_):
        raise RuntimeError("synthetic failure")

    monkeypatch.setattr(domain, "enqueue", fail)
    response = workspace.client.post(
        f"/v1/workspaces/{first['workspace_id']}/runs",
        headers=headers(auth, "run"),
        json={"snapshot_id": first["snapshot_id"]},
    )
    assert response.status_code == 500
    with Session(workspace.app.state.engine) as db:
        assert not list(db.scalars(select(RunRequest)))
        assert len(list(db.scalars(select(IdempotencyRecord)))) == 1


@pytest.mark.parametrize("race", ["autosave", "deletion"])
def test_postgres_workspace_races(race, token, keys):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from types import SimpleNamespace

    from alembic import command
    from fastapi.testclient import TestClient

    from reverse_hr.app import create_app
    from reverse_hr.migrate import migration_config

    url = os.getenv("HR_TEST_CODING_WORKSPACE_DATABASE_URL")
    if not url:
        pytest.skip("Workspace PostgreSQL not configured")
    config = Settings(service_name="coding-workspace", database_url=url)
    command.upgrade(migration_config(config), "head")
    app = create_app(config)
    # This test exercises database serialization; admission is separately tested with signatures.
    app.state.processing_access = SimpleNamespace(check=lambda *_: None)
    app.state.stage_access = SimpleNamespace(check_stage=lambda *_: "code")
    app.state.token_verifier.jwks.fetch_data = lambda: {"keys": [keys[1]]}
    subject = uuid4()
    auth = token(subject)
    body = {
        "session_id": str(uuid4()),
        "stage_id": str(uuid4()),
        "files": [{"path": "main.py", "content": "original"}],
    }
    barrier = Barrier(2)
    with TestClient(app) as client:
        if race == "autosave":
            first = client.post("/v1/workspaces", headers=headers(auth), json=body)
            assert first.status_code == 201
            path = f"/v1/workspaces/{first.json()['workspace_id']}"

            def save(index):
                barrier.wait(timeout=5)
                return client.put(
                    path + "/files",
                    headers=headers(auth, f"save-{index}", 1),
                    json={"files": [{"path": "main.py", "content": str(index)}]},
                ).status_code

            with ThreadPoolExecutor(max_workers=2) as pool:
                assert sorted(pool.map(save, [1, 2])) == [200, 409]
            assert client.get(path, headers=auth).json()["version"] == 2
        else:
            request_id = uuid4()
            event = EventEnvelope(
                event_type="privacy.deletion_requested.v1",
                producer="privacy",
                correlation_id=uuid4(),
                aggregate_id=request_id,
                aggregate_version=1,
                payload={"candidate_id": subject, "request_id": request_id},
            )

            def create_draft():
                barrier.wait(timeout=5)
                return client.post("/v1/workspaces", headers=headers(auth), json=body).status_code

            def remove():
                barrier.wait(timeout=5)
                with Session(app.state.engine) as db, db.begin():
                    process_deletion_request(db, event)

            with ThreadPoolExecutor(max_workers=2) as pool:
                creating, removing = pool.submit(create_draft), pool.submit(remove)
                assert creating.result() in {201, 409}
                removing.result()
            with Session(app.state.engine) as db:
                assert db.get(WorkspaceSubject, str(subject)).blocked
                assert not list(
                    db.scalars(select(Workspace).where(Workspace.candidate_id == str(subject)))
                )
            assert (
                client.post("/v1/workspaces", headers=headers(auth), json=body).status_code == 409
            )


def test_privacy_blocks_workspace_before_local_deletion(workspace_setup, service):
    from test_processing_access import connect_access

    workspace, _, auth, subject, _, signatures = workspace_setup
    privacy = service("privacy")
    privacy.app.state.privacy_signatures = signatures["privacy"]
    workspace.app.state.processing_access = connect_access("coding-workspace", privacy, signatures)
    first = create(workspace_setup)
    path = f"/v1/workspaces/{first['workspace_id']}"
    assert workspace.client.get(path, headers=auth).status_code == 200
    response = privacy.client.post("/v1/deletion-requests", headers=headers(auth, "delete"))
    assert response.status_code == 202, response.text
    assert workspace.client.get(path, headers=auth).status_code == 409
    with Session(workspace.app.state.engine) as db:
        assert db.get(Workspace, first["workspace_id"]) is not None
        assert not db.get(WorkspaceSubject, str(subject)).blocked
