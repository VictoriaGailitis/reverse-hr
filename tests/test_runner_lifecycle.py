from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from runner_monitor_support import drain_monitors
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_code_runner import accept, deletion
from test_code_runner import runner_setup as runner_setup_fixture

from reverse_hr.db import Outbox
from reverse_hr.domains.code_runner import (
    ExecutionAttempt,
    Job,
    RunnerSubject,
    diagnose_one,
    process_deletion_request,
    reserve_attempt,
)
from reverse_hr.migrate import migration_config
from reverse_hr.runner_lifecycle import execution_scope, recover_one
from reverse_hr.sandbox import CleanupUnconfirmed, NsjailExecutor
from reverse_hr.settings import Settings


@pytest.fixture
def prepared(service, token, tmp_path, monkeypatch):
    drain_monitors(monkeypatch)
    setup = runner_setup_fixture.__wrapped__(service, token)
    assert accept(setup)
    scratch, groups = tmp_path / "scratch", tmp_path / "cgroups"
    scratch.mkdir(mode=0o700)
    groups.mkdir()
    executor = NsjailExecutor(
        Settings(
            service_name="code-runner",
            runner_scratch=str(scratch),
            runner_cgroup_parent=str(groups),
        )
    )
    # No real Linux/cgroup execution: exercise durable ledger and actual local file locks only.
    monkeypatch.setattr(executor, "validate", lambda: None)
    node = uuid4()
    engine, access = setup[0].app.state.engine, setup[8]
    attempt = reserve_attempt(engine, access, node, executor)
    assert attempt
    return setup, executor, node, attempt


def events(engine):
    with Session(engine) as db:
        return [row.envelope["event_type"] for row in db.scalars(select(Outbox))]


def remove(setup):
    event = deletion(setup[4])
    with Session(setup[0].app.state.engine) as db, db.begin():
        process_deletion_request(db, event)
    return event


def test_reservation_unique_and_diagnostics_wait(prepared):
    setup, executor, node, attempt = prepared
    engine, access = setup[0].app.state.engine, setup[8]
    assert reserve_attempt(engine, access, node, executor) is None
    assert not diagnose_one(engine, access)
    with Session(engine) as db:
        row = db.get(ExecutionAttempt, str(attempt))
        assert row.state == "reserved" and row.node_id == str(node)
    assert recover_one(engine, node, executor)
    assert not recover_one(engine, node, executor)
    assert not diagnose_one(engine, access)
    with Session(engine) as db:
        assert db.get(Job, setup[6]["run_id"]).error_code == "executor_interrupted"


def test_deletion_waits_for_physical_cleanup_and_blocks_late_worker(prepared):
    setup, executor, node, attempt = prepared
    engine, access = setup[0].app.state.engine, setup[8]
    root, _ = executor.attempt_paths(attempt)
    root.mkdir()
    (root / "source.py").write_text("synthetic private data")
    event = remove(setup)
    assert events(engine) == ["code-runner.data_restricted.v1"]
    assert root.exists()
    with pytest.raises(HTTPException):
        with execution_scope(engine, access, node, attempt, executor):
            pytest.fail("Blocked worker admitted")
    assert recover_one(engine, node, executor)
    assert not root.exists()
    assert events(engine) == ["code-runner.data_restricted.v1", "code-runner.data_deleted.v1"]
    with Session(engine) as db, db.begin():
        assert not list(db.scalars(select(Job)))
        assert not list(db.scalars(select(ExecutionAttempt)))
        subject = db.get(RunnerSubject, str(setup[4]))
        assert subject.blocked and subject.deletion_status == "deleted"
        process_deletion_request(db, event.model_copy(update={"event_id": uuid4()}))
    assert events(engine) == ["code-runner.data_restricted.v1", "code-runner.data_deleted.v1"]
    assert reserve_attempt(engine, access, node, executor) is None


def test_live_guard_blocks_recovery_and_cleanup_failure_retains_obligation(prepared, monkeypatch):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    with execution_scope(engine, setup[8], node, attempt, executor):
        remove(setup)
        with pytest.raises(CleanupUnconfirmed):
            recover_one(engine, node, executor)
    real_clean = executor.cleanup_attempt
    monkeypatch.setattr(executor, "cleanup_attempt", Mock(side_effect=CleanupUnconfirmed))
    with pytest.raises(CleanupUnconfirmed):
        recover_one(engine, node, executor)
    assert events(engine) == ["code-runner.data_restricted.v1"]
    with Session(engine) as db:
        assert db.get(ExecutionAttempt, str(attempt)).state == "cleaning"
    monkeypatch.setattr(executor, "cleanup_attempt", real_clean)
    assert recover_one(engine, node, executor)
    assert events(engine)[-1] == "code-runner.data_deleted.v1"


def test_wrong_node_or_changed_directory_cannot_confirm_cleanup(prepared):
    setup, executor, node, _ = prepared
    engine = setup[0].app.state.engine
    remove(setup)
    assert not recover_one(engine, uuid4(), executor)
    old = executor.settings.runner_scratch
    from pathlib import Path

    Path(old).rename(old + "-previous")
    Path(old).mkdir(mode=0o700)
    assert not recover_one(engine, node, executor)
    assert events(engine) == ["code-runner.data_restricted.v1"]


def test_stale_worker_cannot_start_after_recovery(prepared):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    assert recover_one(engine, node, executor)
    with pytest.raises(HTTPException):
        with execution_scope(engine, setup[8], node, attempt, executor):
            pytest.fail("Recovered attempt admitted")


def test_cleanup_rejects_symlink_and_retries_after_operator_repair(prepared, tmp_path):
    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    root, _ = executor.attempt_paths(attempt)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "retained").touch()
    root.symlink_to(outside)
    remove(setup)
    with pytest.raises(CleanupUnconfirmed):
        recover_one(engine, node, executor)
    assert (outside / "retained").exists()
    assert events(engine) == ["code-runner.data_restricted.v1"]
    root.unlink()
    assert recover_one(engine, node, executor)


def test_downgrade_refuses_cleanup_obligation_before_ddl(prepared):
    setup, _, _, attempt = prepared
    engine = setup[0].app.state.engine
    with pytest.raises(RuntimeError, match="cleanup obligations"):
        command.downgrade(migration_config(setup[0].app.state.settings), "0002_runner")
    with Session(engine) as db:
        assert db.get(ExecutionAttempt, str(attempt))
    assert setup[0].client.get("/health/ready").status_code == 200


def test_reservation_source_failure_rolls_back(service, token, tmp_path, monkeypatch):
    setup = runner_setup_fixture.__wrapped__(service, token)
    assert accept(setup)
    executor = Mock()
    executor.cleanup_scope.return_value = "a" * 64
    monkeypatch.setattr(setup[8], "fetch", Mock(side_effect=HTTPException(503)))
    with pytest.raises(HTTPException):
        reserve_attempt(setup[0].app.state.engine, setup[8], uuid4(), executor)
    with Session(setup[0].app.state.engine) as db:
        assert not list(db.scalars(select(ExecutionAttempt)))


def test_cleanup_before_failed_final_commit_is_retryable(prepared, monkeypatch):
    from reverse_hr.domains import code_runner

    setup, executor, node, attempt = prepared
    engine = setup[0].app.state.engine
    root, _ = executor.attempt_paths(attempt)
    root.mkdir()
    (root / "source").touch()
    remove(setup)
    real_enqueue = code_runner.enqueue
    monkeypatch.setattr(code_runner, "enqueue", Mock(side_effect=RuntimeError("synthetic")))
    with pytest.raises(RuntimeError):
        recover_one(engine, node, executor)
    assert not root.exists()
    assert events(engine) == ["code-runner.data_restricted.v1"]
    with Session(engine) as db:
        assert db.get(ExecutionAttempt, str(attempt)).state == "cleaning"
    monkeypatch.setattr(code_runner, "enqueue", real_enqueue)
    assert recover_one(engine, node, executor)
    assert events(engine)[-1] == "code-runner.data_deleted.v1"


def test_deletion_waits_for_all_nodes_and_preserves_correlation(prepared):
    from datetime import UTC, datetime

    setup, executor, node, _ = prepared
    engine = setup[0].app.state.engine
    other_node = uuid4()
    with Session(engine) as db, db.begin():
        db.add(
            ExecutionAttempt(
                attempt_id=str(uuid4()),
                run_id=str(uuid4()),
                candidate_id=str(setup[4]),
                node_id=str(other_node),
                scope_id=executor.cleanup_scope(),
                state="reserved",
                created_at=datetime.now(UTC),
            )
        )
    event = remove(setup)
    assert recover_one(engine, node, executor)
    assert events(engine) == ["code-runner.data_restricted.v1"]
    assert recover_one(engine, other_node, executor)
    assert events(engine)[-1] == "code-runner.data_deleted.v1"
    with Session(engine) as db:
        for row in db.scalars(select(Outbox)):
            assert row.envelope["correlation_id"] == str(event.correlation_id)
            assert row.envelope["aggregate_version"] == 1


def test_recovery_worker_requires_explicit_node_and_validated_runtime(monkeypatch):
    import sys

    from reverse_hr import worker

    monkeypatch.setattr(sys, "argv", ["worker", "recover"])
    monkeypatch.setattr(worker, "Settings", lambda: Settings(service_name="code-runner"))
    with pytest.raises(SystemExit) as missing:
        worker.main()
    assert missing.value.code == 2
    monkeypatch.setattr(
        worker, "Settings", lambda: Settings(service_name="code-runner", runner_node_id=uuid4())
    )
    with pytest.raises(SystemExit) as disabled:
        worker.main()
    assert disabled.value.code == 2


def test_lock_inode_persists_and_shared_scratch_is_rejected(prepared):
    from reverse_hr.sandbox import SandboxUnavailable

    _, executor, _, attempt = prepared
    root, _ = executor.attempt_paths(attempt)
    lock = root.with_name(root.name + ".lock")
    with executor.attempt_guard(attempt):
        inode = lock.stat().st_ino
        with pytest.raises(CleanupUnconfirmed):
            with executor.attempt_guard(attempt):
                pytest.fail("Double admission")
    with executor.attempt_guard(attempt):
        assert lock.stat().st_ino == inode
    root.parent.chmod(0o755)
    with pytest.raises(SandboxUnavailable):
        executor.cleanup_scope()


def test_deterministic_sandbox_directory_matches_journal(tmp_path, monkeypatch):
    from test_sandbox import adapter_fixture

    executor, spawn = adapter_fixture(tmp_path, monkeypatch)
    tmp_path.chmod(0o700)
    attempt = uuid4()
    root, group = executor.attempt_paths(attempt)
    observed = []

    def capture(_):
        from reverse_hr.sandbox import Outcome

        assert root.name == group.name == f"hr-jail-{attempt}"
        assert (root / "workspace/main.py").read_text() == "synthetic"
        observed.append(root)
        return Outcome("executed", exit_code=0)

    monkeypatch.setattr("reverse_hr.sandbox.capture", capture)
    with executor.attempt_guard(attempt):
        executor.execute(
            "code", {"files": [{"path": "main.py", "content": "synthetic"}]}, attempt_id=attempt
        )
    assert observed == [root] and not root.exists() and not group.exists()
    spawn.assert_called_once()
