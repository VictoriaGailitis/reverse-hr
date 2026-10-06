from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_runner_lifecycle import prepared as prepared_fixture

from reverse_hr.domains.code_runner import (
    ExecutionAttempt,
    Job,
    RunnerControl,
    diagnose_one,
    require_runner_mode,
)
from reverse_hr.runner_control import set_mode
from reverse_hr.runner_lifecycle import run_one
from reverse_hr.runner_readiness import ProbeRecord, fingerprint, require_execution_ready
from reverse_hr.sandbox import Outcome, SandboxUnavailable


@pytest.fixture
def ready(service, token, tmp_path, monkeypatch):
    setup, executor, node, attempt = prepared_fixture.__wrapped__(
        service, token, tmp_path, monkeypatch
    )
    # Synthetic proof validates the gate/worker contract, never certifies actual Linux isolation.
    config = executor.settings
    config.runner_execution_enabled = True
    config.runner_node_id = node
    config.runner_verification_file = str(tmp_path / "probe-record.json")
    path = tmp_path / "probe-record.json"
    proof = ProbeRecord(
        node_id=node, checked_at=datetime.now(UTC), fingerprint=fingerprint(executor), passed=12
    )
    path.write_text(proof.model_dump_json())
    path.chmod(0o600)
    # Fixture reservation was only setup. Start worker tests with an unclaimed queue.
    with Session(setup[0].app.state.engine) as db, db.begin():
        db.delete(db.get(ExecutionAttempt, str(attempt)))
    return setup, executor, node, proof, path


def test_execution_worker_completes_once_and_idle_does_not_repeat(ready, monkeypatch):
    setup, executor, _, _, _ = ready
    engine = setup[0].app.state.engine
    fake = Mock(return_value=Outcome("executed", stdout="synthetic", exit_code=0))
    monkeypatch.setattr(executor, "execute", fake)
    assert run_one(engine, setup[8], executor)
    assert not run_one(engine, setup[8], executor)
    fake.assert_called_once()
    with Session(engine) as db:
        assert db.get(Job, setup[6]["run_id"]).status == "executed"
        assert db.get(RunnerControl, 1).mode == "execution"
    with pytest.raises(HTTPException):
        diagnose_one(engine, setup[8])


def test_execution_recovers_crash_before_claiming_new_work(ready, monkeypatch):
    from reverse_hr.domains.code_runner import reserve_attempt

    setup, executor, node, _, _ = ready
    engine = setup[0].app.state.engine
    attempt = reserve_attempt(engine, setup[8], node, executor, required_mode="execution")
    fake = Mock()
    monkeypatch.setattr(executor, "execute", fake)
    assert run_one(engine, setup[8], executor)
    assert not run_one(engine, setup[8], executor)
    fake.assert_not_called()
    with Session(engine) as db:
        assert db.get(ExecutionAttempt, str(attempt)).state == "cleaned"
        row = db.get(Job, setup[6]["run_id"])
        assert row.status == "technical_error" and row.error_code == "executor_interrupted"


def test_changed_cleanup_scope_prevents_claim_and_fake_confirmation(ready, monkeypatch):
    from reverse_hr.domains.code_runner import reserve_attempt

    setup, executor, node, _, _ = ready
    engine = setup[0].app.state.engine
    attempt = reserve_attempt(engine, setup[8], node, executor, required_mode="execution")
    with Session(engine) as db, db.begin():
        db.get(ExecutionAttempt, str(attempt)).scope_id = "a" * 64
    fake = Mock()
    monkeypatch.setattr(executor, "execute", fake)
    with pytest.raises(SandboxUnavailable):
        run_one(engine, setup[8], executor)
    fake.assert_not_called()


@pytest.mark.parametrize(
    "alter",
    [
        "missing",
        "disabled",
        "expired",
        "future",
        "naive",
        "node",
        "fingerprint",
        "public",
        "symlink",
        "malformed",
    ],
)
def test_readiness_refuses_invalid_probe_records(ready, alter, monkeypatch):
    _, executor, _, proof, path = ready
    config = executor.settings
    if alter == "missing":
        path.unlink()
    elif alter == "disabled":
        config.runner_execution_enabled = False
    elif alter in {"expired", "future", "naive", "node", "fingerprint"}:
        changes = {
            "expired": {"checked_at": datetime.now(UTC) - timedelta(hours=25)},
            "future": {"checked_at": datetime.now(UTC) + timedelta(hours=1)},
            "naive": {"checked_at": datetime.now()},
            "node": {"node_id": uuid4()},
            "fingerprint": {"fingerprint": "0" * 64},
        }
        path.write_text(proof.model_copy(update=changes[alter]).model_dump_json())
    elif alter == "public":
        path.chmod(0o644)
    elif alter == "symlink":
        original = path.with_suffix(".original")
        path.rename(original)
        path.symlink_to(original)
    elif alter == "malformed":
        path.write_text("{}")
    with pytest.raises(SandboxUnavailable):
        require_execution_ready(executor)


def test_record_bound_to_artifact_pins_and_sources(ready):
    _, executor, _, _, _ = ready
    require_execution_ready(executor)
    executor.settings.runner_nsjail_sha256 = "0" * 64
    with pytest.raises(SandboxUnavailable):
        require_execution_ready(executor)


def test_expired_record_halts_new_claims(ready, monkeypatch):
    setup, executor, _, proof, path = ready
    path.write_text(
        proof.model_copy(
            update={"checked_at": datetime.now(UTC) - timedelta(hours=25)}
        ).model_dump_json()
    )
    fake = Mock()
    monkeypatch.setattr(executor, "execute", fake)
    with pytest.raises(SandboxUnavailable):
        run_one(setup[0].app.state.engine, setup[8], executor)
    fake.assert_not_called()
    with Session(setup[0].app.state.engine) as db:
        assert db.get(Job, setup[6]["run_id"]).status == "pending_executor"


def test_mode_switch_stops_old_diagnostics_and_requires_cleanup(ready):
    from reverse_hr.domains.code_runner import reserve_attempt
    from reverse_hr.runner_lifecycle import recover_one

    setup, executor, node, _, _ = ready
    engine = setup[0].app.state.engine
    with Session(engine) as db, db.begin():
        require_runner_mode(db, "diagnostic")
    with pytest.raises(HTTPException):
        run_one(engine, setup[8], executor)
    assert set_mode(engine, "execution", 1) == 2
    with pytest.raises(HTTPException):
        diagnose_one(engine, setup[8])
    attempt = reserve_attempt(engine, setup[8], node, executor, required_mode="execution")
    assert attempt
    with pytest.raises(HTTPException):
        set_mode(engine, "diagnostic", 2)
    assert recover_one(engine, node, executor)
    assert set_mode(engine, "diagnostic", 2) == 3
    with pytest.raises(HTTPException):
        set_mode(engine, "execution", 2)


def test_execute_cli_refuses_default_unverified_runtime(monkeypatch):
    import sys

    from reverse_hr import worker
    from reverse_hr.settings import Settings

    monkeypatch.setattr(sys, "argv", ["worker", "execute"])
    monkeypatch.setattr(
        worker, "Settings", lambda: Settings(service_name="code-runner", runner_node_id=uuid4())
    )
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value.code == 2


def test_diagnostics_cli_refuses_execution_flag(monkeypatch):
    import sys

    from reverse_hr import worker
    from reverse_hr.settings import Settings

    monkeypatch.setattr(sys, "argv", ["worker", "diagnose"])
    monkeypatch.setattr(
        worker,
        "Settings",
        lambda: Settings(service_name="code-runner", runner_execution_enabled=True),
    )
    with pytest.raises(SystemExit) as error:
        worker.main()
    assert error.value.code == 2
