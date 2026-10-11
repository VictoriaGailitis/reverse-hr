from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.protocols.processing_access import REQUEST_CONTEXT
from reverse_hr.protocols.runner_exchange import MANIFEST_REQUEST, ManifestAccess, ManifestRequest
from reverse_hr.services.code_runner.consumer import RunnerConsumer
from reverse_hr.services.code_runner.domain.code_runner import (
    Job,
    RunnerSubject,
    diagnose_one,
    process_deletion_request,
    process_run_request,
)
from reverse_hr.shared.db import Inbox, Outbox
from reverse_hr.shared.signing import canonical, sign
from tests.services.coding_workspace.test_coding_workspace import create
from tests.services.coding_workspace.test_coding_workspace import (
    workspace_setup as workspace_setup_fixture,
)
from tests.shared.test_access import headers


@pytest.fixture
def runner_setup(service, token):
    workspace_setup = workspace_setup_fixture.__wrapped__(service, token)
    workspace, assessment, auth, subject, _, signatures = workspace_setup
    workspace.app.state.workspace_signatures = signatures["coding-workspace"]
    snapshot = create(workspace_setup)
    path = f"/v1/workspaces/{snapshot['workspace_id']}"
    requested = workspace.client.post(
        path + "/runs", headers=headers(auth, "run"), json={"snapshot_id": snapshot["snapshot_id"]}
    )
    assert requested.status_code == 202
    run = requested.json()
    with Session(workspace.app.state.engine) as db:
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "coding-workspace.run_requested.v1"
        )
    runner = service("code-runner")
    access = ManifestAccess(runner.app.state.settings)
    access._signatures = signatures["code-runner"]

    def send(body, signature):
        reply = workspace.client.post(
            "/internal/v1/run-manifest",
            content=body,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    access.send_manifest = send
    runner.app.state.manifest_access = access
    return runner, workspace, assessment, auth, subject, snapshot, run, event, access, signatures


def accept(setup, event=None):
    runner, *_, requested, access, _ = setup
    with Session(runner.app.state.engine) as db, db.begin():
        return process_run_request(db, event or requested, access)


def test_intake_pins_source_and_diagnostic_not_score(runner_setup, token):
    runner, workspace, _, auth, _, snapshot, run, event, access, _ = runner_setup
    # A later autosave must not become the source of this earlier run.
    assert (
        workspace.client.put(
            f"/v1/workspaces/{snapshot['workspace_id']}/files",
            headers=headers(auth, "new", 1),
            json={"files": [{"path": "main.py", "content": "changed"}]},
        ).status_code
        == 200
    )
    assert accept(runner_setup)
    assert not accept(runner_setup)
    duplicate = event.model_copy(update={"event_id": uuid4()})
    assert accept(runner_setup, duplicate)
    path = f"/v1/runs/{run['run_id']}"
    initial = runner.client.get(path, headers=auth)
    assert initial.status_code == 200, initial.text
    assert initial.json()["status"] == "pending_executor"
    assert initial.json()["snapshot_version"] == 1
    assert runner.client.get(path, headers=token()).status_code == 404
    assert diagnose_one(runner.app.state.engine, access)
    assert not diagnose_one(runner.app.state.engine, access)
    result = runner.client.get(path, headers=auth).json()
    assert result["status"] == "technical_error"
    assert result["error_code"] == "executor_unavailable"
    assert result["snapshot_id"] == snapshot["snapshot_id"]
    assert "score" not in result and "stdout" not in result
    with Session(runner.app.state.engine) as db:
        jobs = list(db.scalars(select(Job)))
        assert len(jobs) == 1 and jobs[0].digest == snapshot["digest"]
        assert len(list(db.scalars(select(Outbox)))) == 2
        assert "synthetic" not in str([row.envelope for row in db.scalars(select(Outbox))])


def test_manifest_binding_freshness_and_no_unauthorized_files(runner_setup):
    _, workspace, _, _, subject, snapshot, run, _, _, signatures = runner_setup
    body = ManifestRequest(
        candidate_id=subject,
        workspace_id=snapshot["workspace_id"],
        snapshot_id=snapshot["snapshot_id"],
        run_id=run["run_id"],
        nonce=uuid4(),
        requester="code-runner",
        issued_at=datetime.now(UTC),
    )

    def send(req, context=MANIFEST_REQUEST):
        return workspace.client.post(
            "/internal/v1/run-manifest",
            content=canonical(req),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": sign(signatures["code-runner"], context, req),
            },
        )

    reply = send(body)
    assert reply.status_code == 200
    assert reply.json()["manifest"]["files"] == snapshot["files"]
    assert send(body).status_code == 401
    assert send(body.model_copy(update={"nonce": uuid4()}), REQUEST_CONTEXT).status_code == 401
    assert (
        send(
            body.model_copy(
                update={"nonce": uuid4(), "issued_at": datetime.now(UTC) - timedelta(seconds=40)}
            )
        ).status_code
        == 401
    )
    for key in ("candidate_id", "run_id", "workspace_id", "snapshot_id"):
        denied = send(body.model_copy(update={"nonce": uuid4(), key: uuid4()}))
        assert denied.status_code == 200
        assert denied.json()["allowed"] is False
        assert denied.json()["manifest"] is None
        assert "synthetic" not in denied.text


def test_manifest_corruption_or_unavailable_rolls_back_intake(runner_setup):
    runner, _, _, _, _, _, _, event, access, _ = runner_setup
    original = access.send_manifest

    def bad(body, signature):
        data, signed = original(body, signature)
        return data.replace(b"synthetic", b"tampered"), signed

    access.send_manifest = bad
    with pytest.raises(HTTPException) as exc:
        accept(runner_setup)
    assert exc.value.status_code == 503
    with Session(runner.app.state.engine) as db:
        assert not list(db.scalars(select(Job)))
        assert db.get(Inbox, ("code-runner.run_request", str(event.event_id))) is None
        assert not list(db.scalars(select(Outbox)))
    access.send_manifest = original
    assert accept(runner_setup)


def test_denied_intake_and_cancelled_diagnostic_after_consent_withdrawal(runner_setup):
    runner, _, assessment, _, _, _, _, event, access, _ = runner_setup

    def withdrawn(*_):
        raise HTTPException(409)

    assessment.app.state.processing_access.check_assessment = withdrawn
    assert accept(runner_setup)
    with Session(runner.app.state.engine) as db:
        assert not list(db.scalars(select(Job)))
    assessment.app.state.processing_access.check_assessment = lambda *_: None
    assert accept(runner_setup, event.model_copy(update={"event_id": uuid4()}))
    assessment.app.state.processing_access.check_assessment = withdrawn
    assert diagnose_one(runner.app.state.engine, access)
    with Session(runner.app.state.engine) as db:
        row = db.get(Job, str(event.aggregate_id))
        assert row.status == "cancelled" and row.error_code == "access_withdrawn"


def deletion(subject):
    request_id = uuid4()
    return EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )


def test_deletion_prevents_late_event_recreation_and_ack_after_commit(runner_setup):
    runner, _, _, auth, subject, _, run, event, access, signatures = runner_setup
    assert accept(runner_setup)
    deleting = deletion(subject)
    with Session(runner.app.state.engine) as db:
        process_deletion_request(db, deleting)
        db.rollback()
    assert runner.client.get(f"/v1/runs/{run['run_id']}", headers=auth).status_code == 200
    consumer = RunnerConsumer(
        runner.app.state.engine, signatures["code-runner"], runner.app.state.settings
    )
    consumer.access = access
    body, signed = signatures["privacy"].sign(deleting)
    channel = Mock()

    def ack(**_):
        with Session(runner.app.state.engine) as db:
            assert not list(db.scalars(select(Job)))
            assert db.get(RunnerSubject, str(subject)).blocked
            assert [e.envelope["event_type"] for e in db.scalars(select(Outbox))] == [
                "code-runner.data_deleted.v1"
            ]

    channel.basic_ack.side_effect = ack
    consumer(
        channel,
        SimpleNamespace(exchange="events.privacy", delivery_tag=1),
        SimpleNamespace(headers=signed, message_id=str(deleting.event_id)),
        body,
    )
    channel.basic_ack.assert_called_once_with(delivery_tag=1)
    channel.basic_publish.assert_not_called()
    assert accept(runner_setup, event.model_copy(update={"event_id": uuid4()}))
    assert runner.client.get(f"/v1/runs/{run['run_id']}", headers=auth).status_code == 409


def test_signed_intake_ack_commits_job(runner_setup):
    runner, _, _, _, _, _, _, event, access, signatures = runner_setup
    consumer = RunnerConsumer(
        runner.app.state.engine, signatures["code-runner"], runner.app.state.settings
    )
    consumer.access = access
    body, signed = signatures["coding-workspace"].sign(event)
    channel = Mock()

    def ack(**_):
        with Session(runner.app.state.engine) as db:
            assert db.get(Job, str(event.aggregate_id)).status == "pending_executor"

    channel.basic_ack.side_effect = ack
    consumer(
        channel,
        SimpleNamespace(exchange="events.coding-workspace", delivery_tag=1),
        SimpleNamespace(headers=signed, message_id=str(event.event_id)),
        body,
    )
    channel.basic_ack.assert_called_once_with(delivery_tag=1)
    channel.basic_publish.assert_not_called()


def test_diagnostic_failure_does_not_complete_job(runner_setup, monkeypatch):
    import reverse_hr.services.code_runner.domain.code_runner as domain

    runner, _, _, _, _, _, _, event, access, _ = runner_setup
    assert accept(runner_setup)

    def fail(*_):
        raise RuntimeError("synthetic commit failure")

    monkeypatch.setattr(domain, "enqueue", fail)
    with pytest.raises(RuntimeError):
        diagnose_one(runner.app.state.engine, access)
    with Session(runner.app.state.engine) as db:
        assert db.get(Job, str(event.aggregate_id)).status == "pending_executor"
        assert len(list(db.scalars(select(Outbox)))) == 1


def test_workspace_projection_out_of_order_and_replay_are_current(runner_setup):
    from reverse_hr.services.coding_workspace.domain.coding_workspace import process_runner_event

    runner, workspace, _, auth, _, snapshot, run, _, access, _ = runner_setup
    assert accept(runner_setup)
    assert diagnose_one(runner.app.state.engine, access)
    with Session(runner.app.state.engine) as db:
        events = [EventEnvelope.model_validate(row.envelope) for row in db.scalars(select(Outbox))]
    # Deliver terminal event first: a late accepted event cannot regress it.
    for event in sorted(events, key=lambda e: e.aggregate_version, reverse=True):
        with Session(workspace.app.state.engine) as db, db.begin():
            assert process_runner_event(db, event)
        with Session(workspace.app.state.engine) as db, db.begin():
            assert not process_runner_event(db, event)
    path = f"/v1/workspaces/{snapshot['workspace_id']}"
    current = workspace.client.get(path + "/runs/" + run["run_id"], headers=auth).json()
    assert current["status"] == "runner_diagnosed"
    assert current["snapshot_version"] == 1
    assert current["runner_status_path"] == f"/code-runner/v1/runs/{run['run_id']}"
    replay = workspace.client.post(
        path + "/runs", headers=headers(auth, "run"), json={"snapshot_id": snapshot["snapshot_id"]}
    )
    assert replay.status_code == 202 and replay.json() == current
    bad = events[0].model_copy(
        update={"event_id": uuid4(), "payload": events[0].payload | {"snapshot_id": uuid4()}}
    )
    with pytest.raises(HTTPException), Session(workspace.app.state.engine) as db, db.begin():
        process_runner_event(db, bad)


def test_runner_migration_protects_jobs_and_empty_reapply(service, runner_setup):
    from alembic import command

    from reverse_hr.platform.migrate import migration_config

    runner, *_ = runner_setup
    config = migration_config(runner.app.state.settings)
    command.downgrade(config, "0001_transport")
    command.upgrade(config, "head")
    assert accept(runner_setup)
    with pytest.raises(RuntimeError, match="populated runner"):
        command.downgrade(config, "0001_transport")
    assert runner.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("race", ["duplicate", "deletion"])
def test_postgres_intake_serialization(runner_setup, race):
    import os
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier

    from alembic import command

    from reverse_hr.platform.migrate import migration_config
    from reverse_hr.platform.settings import Settings
    from reverse_hr.shared.db import make_engine

    url = os.getenv("HR_TEST_CODE_RUNNER_DATABASE_URL")
    if not url:
        pytest.skip("Code Runner PostgreSQL not configured")
    _, _, _, _, subject, _, _, event, access, _ = runner_setup
    settings = Settings(service_name="code-runner", database_url=url)
    command.upgrade(migration_config(settings), "head")
    engine = make_engine(url)
    barrier = Barrier(2)
    removing = deletion(subject)

    def apply(index):
        barrier.wait(timeout=5)
        with Session(engine) as db, db.begin():
            if race == "deletion" and index == 1:
                return process_deletion_request(db, removing)
            return process_run_request(db, event.model_copy(update={"event_id": uuid4()}), access)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            assert list(pool.map(apply, [0, 1])) == [True, True]
        with Session(engine) as db:
            jobs = list(db.scalars(select(Job).where(Job.candidate_id == str(subject))))
            if race == "duplicate":
                assert len(jobs) == 1
                assert (
                    len(
                        [
                            row
                            for row in db.scalars(select(Outbox))
                            if row.envelope["aggregate_id"] == str(event.aggregate_id)
                        ]
                    )
                    == 1
                )
            else:
                assert not jobs
                assert db.get(RunnerSubject, str(subject)).blocked
        if race == "deletion":
            with Session(engine) as db, db.begin():
                process_run_request(db, event.model_copy(update={"event_id": uuid4()}), access)
            with Session(engine) as db:
                assert not list(db.scalars(select(Job).where(Job.candidate_id == str(subject))))
    finally:
        engine.dispose()
