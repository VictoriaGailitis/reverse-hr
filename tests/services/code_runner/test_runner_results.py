from unittest.mock import Mock

import pytest
from alembic import command
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.runner import Output
from reverse_hr.platform.migrate import migration_config
from reverse_hr.services.code_runner.domain.code_runner import (
    ExecutionAttempt,
    ExecutionResult,
    Job,
)
from reverse_hr.services.code_runner.runner_lifecycle import (
    execute_reserved,
    execution_scope,
    recover_one,
)
from reverse_hr.services.code_runner.sandbox import CleanupUnconfirmed, Outcome
from reverse_hr.services.coding_workspace.domain.coding_workspace import process_runner_event
from reverse_hr.shared.db import Outbox
from tests.services.code_runner.test_runner_lifecycle import events, remove
from tests.services.code_runner.test_runner_lifecycle import prepared as prepared_fixture


@pytest.fixture
def prepared(service, token, tmp_path, monkeypatch):
    return prepared_fixture.__wrapped__(service, token, tmp_path, monkeypatch)


@pytest.mark.parametrize(
    "outcome",
    [
        Outcome("executed", stdout="synthetic success", exit_code=0),
        Outcome("runtime_error", stderr="synthetic error", exit_code=1),
        Outcome("limit_exceeded", reason="output_limit"),
        Outcome(
            "technical_error",
            stdout="private supervisor",
            stderr="private diagnostic",
            reason="sandbox_failed",
        ),
    ],
)
def test_private_result_bound_to_snapshot_and_no_output_in_events(
    prepared, monkeypatch, token, outcome
):
    setup, executor, node, attempt = prepared
    runner, workspace, _, auth, _, snapshot, run, _, access, _ = setup
    engine = runner.app.state.engine
    fake = Mock(return_value=outcome)
    monkeypatch.setattr(executor, "execute", fake)
    path = f"/v1/runs/{run['run_id']}"
    assert runner.client.get(path + "/result", headers=auth).status_code == 404
    assert execute_reserved(engine, access, node, attempt, executor)
    fake.assert_called_once()
    args, kwargs = fake.call_args
    assert args[0] == "code" and args[1].files
    assert kwargs["attempt_id"] == attempt and callable(kwargs["stop_check"])
    result = runner.client.get(path + "/result", headers=auth)
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["snapshot_id"] == snapshot["snapshot_id"] and body["snapshot_version"] == 1
    assert body["status"] == outcome.status and body["demo"]
    assert body["completed_at"].endswith("Z")
    assert body["stdout"] == ("" if outcome.status == "technical_error" else outcome.stdout)
    assert "score" not in body and "passed" not in body
    assert runner.client.get(path + "/result", headers=token()).status_code == 404
    assert runner.client.get(path, headers=auth).json()["version"] == 3
    with Session(engine) as db:
        messages = [EventEnvelope.model_validate(e.envelope) for e in db.scalars(select(Outbox))]
        assert db.get(ExecutionAttempt, str(attempt)).state == "cleaned"
        assert db.get(ExecutionResult, run["run_id"]).attempt_id == str(attempt)
    assert [e.aggregate_version for e in messages] == [1, 2, 3]
    for event in messages:
        assert set(event.payload) == {"candidate_id", "run_id", "workspace_id", "snapshot_id"}
        assert "synthetic" not in event.model_dump_json()
    # Reordered/duplicate terminal delivery cannot regress Workspace projection.
    with Session(workspace.app.state.engine) as db, db.begin():
        for event in reversed(messages):
            process_runner_event(db, event)
            assert not process_runner_event(db, event)
    replay = workspace.client.get(f"/v1/workspaces/{snapshot['workspace_id']}", headers=auth)
    assert replay.status_code == 200
    with Session(workspace.app.state.engine) as db:
        from reverse_hr.services.coding_workspace.domain.coding_workspace import RunRequest

        assert db.get(RunRequest, run["run_id"]).status == "runner_finished"


def test_cleanup_failure_never_publishes_output_and_recovery_records_interruption(
    prepared, monkeypatch
):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    monkeypatch.setattr(executor, "execute", Mock(side_effect=CleanupUnconfirmed))
    with pytest.raises(CleanupUnconfirmed):
        execute_reserved(engine, setup[8], node, attempt, executor)
    with Session(engine) as db:
        assert not list(db.scalars(select(ExecutionResult)))
        assert db.get(Job, setup[6]["run_id"]).status == "running"
    assert events(engine)[-1] == "code-runner.run_started.v1"
    assert recover_one(engine, node, executor)
    with Session(engine) as db:
        row = db.get(ExecutionResult, setup[6]["run_id"])
        assert row.reason == "executor_interrupted" and row.stdout == row.stderr == ""
    assert events(engine)[-1] == "code-runner.run_finished.v1"
    assert not recover_one(engine, node, executor)


def test_deletion_during_execution_discards_result_after_cleanup(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine

    def execute(*_, **__):
        remove(setup)
        return Outcome("executed", stdout="must be discarded", exit_code=0)

    monkeypatch.setattr(executor, "execute", execute)
    assert not execute_reserved(engine, setup[8], node, attempt, executor)
    assert events(engine) == ["code-runner.data_restricted.v1", "code-runner.data_deleted.v1"]
    with Session(engine) as db:
        assert not list(db.scalars(select(ExecutionResult)))
        assert not list(db.scalars(select(Job)))


def test_withdrawn_source_at_completion_cancels_without_output(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine

    def execute(*_, **__):
        monkeypatch.setattr(setup[8], "fetch", lambda *_: None)
        return Outcome("executed", stdout="discarded", exit_code=0)

    monkeypatch.setattr(executor, "execute", execute)
    assert execute_reserved(engine, setup[8], node, attempt, executor)
    with Session(engine) as db:
        result = db.get(ExecutionResult, setup[6]["run_id"])
        assert result.status == "cancelled" and result.reason == "access_withdrawn"
        assert result.stdout == result.stderr == ""
    reply = setup[0].client.get(f"/v1/runs/{setup[6]['run_id']}/result", headers=setup[3])
    assert reply.status_code == 409


def test_result_read_fails_closed_when_source_unavailable(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    monkeypatch.setattr(executor, "execute", Mock(return_value=Outcome("executed", exit_code=0)))
    assert execute_reserved(setup[0].app.state.engine, setup[8], node, attempt, executor)
    monkeypatch.setattr(setup[8], "fetch", Mock(side_effect=HTTPException(503)))
    reply = setup[0].client.get(f"/v1/runs/{setup[6]['run_id']}/result", headers=setup[3])
    assert reply.status_code == 503 and "stdout" not in reply.text


def test_result_commit_failure_keeps_cleanup_ledger_and_no_partial_output(prepared, monkeypatch):
    from reverse_hr.services.code_runner.domain import code_runner

    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    monkeypatch.setattr(
        executor, "execute", Mock(return_value=Outcome("executed", stdout="lost", exit_code=0))
    )
    original = code_runner.enqueue

    def fail_terminal(session, event):
        if event.event_type == "code-runner.run_finished.v1":
            raise RuntimeError("synthetic commit failure")
        return original(session, event)

    monkeypatch.setattr(code_runner, "enqueue", fail_terminal)
    with pytest.raises(RuntimeError):
        execute_reserved(engine, setup[8], node, attempt, executor)
    with Session(engine) as db:
        assert not list(db.scalars(select(ExecutionResult)))
        assert db.get(ExecutionAttempt, str(attempt)).state == "active"
    monkeypatch.setattr(code_runner, "enqueue", original)
    assert recover_one(engine, node, executor)
    with Session(engine) as db:
        result = db.get(ExecutionResult, setup[6]["run_id"])
        assert result.reason == "executor_interrupted" and result.stdout == ""


@pytest.mark.parametrize(
    "bad",
    [
        {"status": "executed", "exit_code": 1},
        {"status": "runtime_error", "exit_code": 0},
        {"status": "limit_exceeded", "reason": "sandbox_failed"},
        {"status": "technical_error", "reason": "sandbox_failed", "stdout": "leak"},
        {"status": "cancelled", "reason": "executor_interrupted"},
        {"status": "executed", "exit_code": True},
        {"status": "executed", "exit_code": 0, "stdout": "я" * 32769},
        {"status": "executed", "exit_code": 0, "stdout": "a" * 40000, "stderr": "b" * 30000},
    ],
)
def test_output_is_bounded_and_coherent(bad):
    with pytest.raises(ValidationError):
        Output.model_validate(bad)


def test_result_purged_and_downgrade_preserves_readiness(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    monkeypatch.setattr(executor, "execute", Mock(return_value=Outcome("executed", exit_code=0)))
    assert execute_reserved(engine, setup[8], node, attempt, executor)
    with pytest.raises(RuntimeError, match="private execution results"):
        command.downgrade(migration_config(setup[0].app.state.settings), "0003_attempts")
    assert setup[0].client.get("/health/ready").status_code == 200
    remove(setup)
    assert events(engine) == ["code-runner.data_deleted.v1"]
    with Session(engine) as db:
        assert not list(db.scalars(select(ExecutionResult)))


def test_second_execution_is_fenced(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    monkeypatch.setattr(executor, "execute", Mock(return_value=Outcome("executed", exit_code=0)))
    assert execute_reserved(setup[0].app.state.engine, setup[8], node, attempt, executor)
    with pytest.raises(HTTPException):
        with execution_scope(setup[0].app.state.engine, setup[8], node, attempt, executor):
            pytest.fail("Repeated execution admitted")
    executor.execute.assert_called_once()


def test_source_unavailable_at_completion_retains_obligation(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine

    def execute(*_, **__):
        monkeypatch.setattr(setup[8], "fetch", Mock(side_effect=HTTPException(503)))
        return Outcome("executed", stdout="discarded", exit_code=0)

    monkeypatch.setattr(executor, "execute", execute)
    with pytest.raises(HTTPException):
        execute_reserved(engine, setup[8], node, attempt, executor)
    with Session(engine) as db:
        assert db.get(ExecutionAttempt, str(attempt)).state == "active"
        assert not list(db.scalars(select(ExecutionResult)))
    assert recover_one(engine, node, executor)
    with Session(engine) as db:
        assert db.get(ExecutionResult, setup[6]["run_id"]).reason == "executor_interrupted"


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("private host error"),
        Outcome("executed", stdout="a" * 65537, exit_code=0),
    ],
)
def test_executor_failure_or_invalid_output_is_redacted(prepared, monkeypatch, failure):
    setup, executor, node, attempt = prepared
    fake = (
        Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    )
    monkeypatch.setattr(executor, "execute", fake)
    assert execute_reserved(setup[0].app.state.engine, setup[8], node, attempt, executor)
    with Session(setup[0].app.state.engine) as db:
        result = db.get(ExecutionResult, setup[6]["run_id"])
        assert result.status == "technical_error" and result.reason == "sandbox_failed"
        assert result.stdout == result.stderr == ""
        assert db.get(ExecutionAttempt, str(attempt)).state == "cleaned"
