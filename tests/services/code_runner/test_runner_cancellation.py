import threading
import time
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.services.code_runner.domain.code_runner import (
    ExecutionAttempt,
    ExecutionResult,
    Job,
)
from reverse_hr.services.code_runner.runner_lifecycle import (
    execute_reserved,
    execution_scope,
    recover_one,
    stop_reason,
)
from reverse_hr.services.code_runner.runner_monitor import StopMonitor
from reverse_hr.services.code_runner.sandbox import CleanupUnconfirmed, Outcome, capture
from reverse_hr.services.coding_workspace.domain.coding_workspace import (
    RunRequest,
    process_runner_event,
)
from reverse_hr.shared.db import IdempotencyRecord, Outbox
from tests.services.code_runner.test_code_runner import accept
from tests.services.code_runner.test_code_runner import runner_setup as runner_setup_fixture
from tests.services.code_runner.test_runner_lifecycle import events, remove
from tests.services.code_runner.test_runner_lifecycle import prepared as prepared_fixture
from tests.services.code_runner.test_sandbox import control
from tests.shared.test_access import headers


@pytest.fixture
def prepared(service, token, tmp_path, monkeypatch):
    return prepared_fixture.__wrapped__(service, token, tmp_path, monkeypatch)


def cancel(setup, key="cancel", version=1, auth=None):
    return setup[0].client.post(
        f"/v1/runs/{setup[6]['run_id']}/cancel", headers=headers(auth or setup[3], key, version)
    )


def test_pending_without_attempt_cancels_immediately_and_replays_current(service, token):
    setup = runner_setup_fixture.__wrapped__(service, token)
    assert accept(setup)
    assert cancel(setup, auth=token()).status_code == 404
    assert cancel(setup, version=9).status_code == 409
    first = cancel(setup)
    assert first.status_code == 202, first.text
    assert first.json()["status"] == "cancelled" and first.json()["error_code"] == "user_cancelled"
    assert first.json()["cancel_requested"] and first.json()["version"] == 2
    assert cancel(setup).json() == first.json()
    assert cancel(setup, version=2).status_code == 409  # Same key, different command hash.
    assert events(setup[0].app.state.engine) == [
        "code-runner.run_accepted.v1",
        "code-runner.run_cancelled.v1",
    ]
    with Session(setup[0].app.state.engine) as db:
        messages = [
            EventEnvelope.model_validate(row.envelope) for row in db.scalars(select(Outbox))
        ]
    with Session(setup[1].app.state.engine) as db, db.begin():
        for event in reversed(messages):
            process_runner_event(db, event)
        assert db.get(RunRequest, setup[6]["run_id"]).status == "runner_cancelled"


def test_reserved_cancel_waits_for_cleanup_and_fences_start(prepared):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    reply = cancel(setup)
    assert reply.status_code == 202 and reply.json()["status"] == "pending_executor"
    assert reply.json()["cancel_requested"]
    with pytest.raises(HTTPException):
        with execution_scope(engine, setup[8], node, attempt, executor):
            pytest.fail("Cancellation bypassed")
    assert recover_one(engine, node, executor)
    assert cancel(setup).json()["status"] == "cancelled"
    assert events(engine)[-1] == "code-runner.run_cancelled.v1"
    with Session(engine) as db:
        assert db.get(ExecutionAttempt, str(attempt)).state == "cleaned"
        assert not list(db.scalars(select(ExecutionResult)))


def test_active_cancel_is_observed_and_output_discarded(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine

    def execute(*_, stop_check, **__):
        requested = cancel(setup, version=2)
        assert requested.status_code == 202 and requested.json()["status"] == "running"
        assert stop_reason(engine, setup[8], attempt) == "user_cancelled"
        assert callable(stop_check)
        return Outcome("executed", stdout="discard this output", exit_code=0)

    monkeypatch.setattr(executor, "execute", execute)
    assert execute_reserved(engine, setup[8], node, attempt, executor)
    replay = cancel(setup, version=2).json()
    assert replay["status"] == "cancelled" and replay["version"] == 3
    with Session(engine) as db:
        result = db.get(ExecutionResult, setup[6]["run_id"])
        assert result.reason == "user_cancelled" and result.stdout == result.stderr == ""
    assert events(engine)[-1] == "code-runner.run_cancelled.v1"


def test_cancel_cleanup_failure_holds_running_until_recovery(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine

    def execute(*_, **__):
        assert cancel(setup, version=2).status_code == 202
        raise CleanupUnconfirmed()

    monkeypatch.setattr(executor, "execute", execute)
    with pytest.raises(CleanupUnconfirmed):
        execute_reserved(engine, setup[8], node, attempt, executor)
    assert cancel(setup, version=2).json()["status"] == "running"
    assert recover_one(engine, node, executor)
    assert cancel(setup, version=2).json()["status"] == "cancelled"
    with Session(engine) as db:
        assert db.get(ExecutionResult, setup[6]["run_id"]).reason == "user_cancelled"


def test_terminal_result_cannot_be_replaced_by_cancel(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    monkeypatch.setattr(executor, "execute", Mock(return_value=Outcome("executed", exit_code=0)))
    assert execute_reserved(setup[0].app.state.engine, setup[8], node, attempt, executor)
    assert cancel(setup, version=3).status_code == 409
    with Session(setup[0].app.state.engine) as db:
        assert not db.get(Job, setup[6]["run_id"]).cancel_requested
        assert db.get(ExecutionResult, setup[6]["run_id"]).status == "executed"


def test_cancel_after_source_withdrawal_requires_no_source_read(prepared, monkeypatch):
    setup, _, _, _ = prepared
    monkeypatch.setattr(setup[8], "fetch", Mock(side_effect=HTTPException(503)))
    assert cancel(setup).status_code == 202
    setup[8].fetch.assert_not_called()


def test_deletion_purges_cancel_command_replies_and_late_replay_is_blocked(prepared):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    assert cancel(setup).status_code == 202
    remove(setup)
    with Session(engine) as db:
        assert not list(db.scalars(select(IdempotencyRecord)))
    assert cancel(setup).status_code == 409
    assert recover_one(engine, node, executor)
    assert events(engine)[-1] == "code-runner.data_deleted.v1"


def test_stop_reason_checks_fresh_admission_and_permanent_tombstone(prepared, monkeypatch):
    setup, _, _, attempt = prepared
    engine = setup[0].app.state.engine
    assert stop_reason(engine, setup[8], attempt) is None
    assert stop_reason(engine, setup[8], uuid4()) == "access_withdrawn"
    monkeypatch.setattr(setup[8], "fetch", lambda *_: None)
    assert stop_reason(engine, setup[8], attempt) == "access_withdrawn"
    remove(setup)
    assert stop_reason(engine, setup[8], attempt) == "access_withdrawn"


@pytest.mark.parametrize("reason", ["user_cancelled", "access_withdrawn", "admission_unavailable"])
@pytest.mark.parametrize("closed_pipes", [False, True])
def test_collector_stops_trusted_control_process_without_output(reason, closed_pipes):
    # Fixed trusted fixture programs, never candidate code on the host.
    source = "import time; time.sleep(10)"
    if closed_pipes:
        source = "import os,time; os.close(1); os.close(2); time.sleep(10)"
    started = time.monotonic()
    outcome = capture(
        control(source), stop_check=lambda: reason if time.monotonic() - started > 0.1 else None
    )
    assert time.monotonic() - started < 1.5
    assert outcome.reason == reason and not outcome.stdout and not outcome.stderr
    assert outcome.status == (
        "technical_error" if reason == "admission_unavailable" else "cancelled"
    )


def test_stalled_monitor_is_bounded_fail_closed_and_cannot_grow_threads():
    entered, release = threading.Event(), threading.Event()

    def stalled():
        entered.set()
        release.wait(3)
        return None

    monitor = StopMonitor(stalled, max_age=0.03)
    try:
        with monitor:
            assert entered.wait(1)
            outcome = capture(control("import time; time.sleep(10)"), stop_check=monitor.current)
            assert outcome.reason == "admission_unavailable"
            with StopMonitor(lambda: None) as another:
                assert another.thread is None and another.current() == "admission_unavailable"
    finally:
        release.set()
        monitor.thread.join(timeout=1)
    assert not monitor.thread.is_alive()


def test_monitor_exceptions_are_redacted_and_cancel_reason_is_sticky():
    called = threading.Event()

    def failed():
        called.set()
        raise RuntimeError("private URL credentials")

    with StopMonitor(failed) as monitor:
        assert called.wait(1)
        monitor.thread.join(timeout=1)
        assert monitor.current() == "admission_unavailable"
    with StopMonitor(lambda: "user_cancelled") as monitor:
        monitor.thread.join(timeout=1)
        assert monitor.current() == "user_cancelled"


def test_cancel_event_failure_rolls_back_intent_and_cached_reply(service, token, monkeypatch):
    from reverse_hr.services.code_runner.domain import code_runner

    setup = runner_setup_fixture.__wrapped__(service, token)
    assert accept(setup)
    original = code_runner.run_event
    monkeypatch.setattr(code_runner, "run_event", Mock(side_effect=RuntimeError("synthetic")))
    reply = cancel(setup)
    assert reply.status_code == 500
    with Session(setup[0].app.state.engine) as db:
        job = db.get(Job, setup[6]["run_id"])
        assert job.status == "pending_executor" and not job.cancel_requested and job.version == 1
        assert not list(db.scalars(select(IdempotencyRecord)))
    assert events(setup[0].app.state.engine) == ["code-runner.run_accepted.v1"]
    monkeypatch.setattr(code_runner, "run_event", original)
    assert cancel(setup).status_code == 202


@pytest.mark.parametrize("reason", ["user_cancelled", "admission_unavailable"])
def test_adapter_checks_stop_before_spawn_and_cleans_private_files(tmp_path, monkeypatch, reason):
    from tests.services.code_runner.test_sandbox import adapter_fixture

    executor, spawn = adapter_fixture(tmp_path, monkeypatch)
    outcome = executor.execute(
        "code",
        {"files": [{"path": "main.py", "content": "synthetic"}]},
        stop_check=lambda: reason,
    )
    assert outcome.reason == reason and not outcome.stdout and not outcome.stderr
    assert outcome.status == ("cancelled" if reason == "user_cancelled" else "technical_error")
    spawn.assert_not_called()
    assert not list(tmp_path.glob("hr-jail-*"))
