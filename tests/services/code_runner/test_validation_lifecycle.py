"""Real SQLite/OS locks; synthetic readiness/admission, no sandbox execution."""

from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import reverse_hr.services.code_runner.validation_lifecycle as domain
from reverse_hr.platform.migrate import migration_config
from reverse_hr.platform.settings import Settings
from reverse_hr.services.code_runner.domain.code_runner import (
    RunnerSubject,
    process_deletion_request,
    require_runner_mode,
)
from reverse_hr.services.code_runner.sandbox import (
    CleanupUnconfirmed,
    NsjailExecutor,
    SandboxUnavailable,
)
from tests.services.code_runner.test_code_runner import deletion
from tests.services.code_runner.test_test_harness import setup as harness_setup


@pytest.fixture
def setup(service, tmp_path, monkeypatch):
    target = service("code-runner")
    suite, _, plan, _ = harness_setup.__wrapped__()
    scratch, groups = tmp_path / "scratch", tmp_path / "groups"
    scratch.mkdir(mode=0o700)
    groups.mkdir()
    node, owner = uuid4(), uuid4()
    executor = NsjailExecutor(
        Settings(
            service_name="code-runner",
            runner_node_id=node,
            runner_scratch=str(scratch),
            runner_cgroup_parent=str(groups),
        )
    )
    monkeypatch.setattr(executor, "validate", lambda: None)
    access = target.app.state.processing_access
    engine = target.app.state.engine
    domain.register(engine, owner, access, suite, plan)
    attempt = domain.reserve(engine, owner, plan.validation_id, access, node, executor)
    admission = SimpleNamespace(check=Mock(return_value=None))
    # These doubles do not create a probe record or authorize a real worker.
    monkeypatch.setattr(domain, "require_execution_ready", lambda *_: None)
    monkeypatch.setattr(domain, "fingerprint", lambda *_: plan.pin.runtime_fingerprint)
    return SimpleNamespace(
        target=target,
        engine=engine,
        suite=suite,
        plan=plan,
        owner=owner,
        node=node,
        executor=executor,
        access=access,
        attempt=attempt,
        admission=admission,
    )


def state(s):
    with Session(s.engine) as session:
        attempt = session.get(domain.ValidationAttempt, str(s.attempt))
        batch = session.get(domain.ValidationBatch, str(s.plan.validation_id))
        return attempt.state if attempt else None, batch.status if batch else None


def scope(s):
    return domain.validation_scope(s.engine, s.access, s.admission, s.node, s.attempt, s.executor)


def remove(s):
    with Session(s.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.owner))


def test_reservation_is_unique_and_recovery_never_reexecutes(setup):
    s = setup
    assert domain.register(s.engine, s.owner, s.access, s.suite, s.plan) == s.plan.validation_id
    assert (
        domain.reserve(s.engine, s.owner, s.plan.validation_id, s.access, s.node, s.executor)
        is None
    )
    assert state(s) == ("reserved", "prepared")
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert state(s) == ("cleaned", "interrupted")
    assert not domain.recover_one(s.engine, s.node, s.executor)
    with pytest.raises(HTTPException):
        domain.reserve(s.engine, s.owner, s.plan.validation_id, s.access, s.node, s.executor)
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Late activation")


def test_active_scope_holds_real_os_lock_and_preserves_cleanup_duty(setup):
    s = setup
    with scope(s) as item:
        assert item == s.plan.inputs[0]
        assert state(s) == ("active", "prepared")
        with pytest.raises(CleanupUnconfirmed):
            domain.recover_one(s.engine, s.node, s.executor)
        with pytest.raises(CleanupUnconfirmed), scope(s):
            pytest.fail("Concurrent activation")
    assert state(s)[0] == "active"
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert state(s) == ("cleaned", "interrupted")


def test_scope_exception_does_not_erase_obligation(setup):
    s = setup
    with pytest.raises(RuntimeError), scope(s):
        raise RuntimeError("Synthetic interrupted caller")
    assert state(s)[0] == "active"
    assert domain.recover_one(s.engine, s.node, s.executor)


@pytest.mark.parametrize("failure", [409, 503])
def test_fresh_admission_or_permission_failure_keeps_reserved(setup, failure):
    s = setup
    s.admission.check.side_effect = HTTPException(failure)
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Denied admission")
    assert state(s)[0] == "reserved"
    s.admission.check.side_effect = None
    s.access.check = Mock(side_effect=HTTPException(failure))
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Denied processing")
    assert state(s)[0] == "reserved"


@pytest.mark.parametrize("gate", ["probe", "fingerprint", "node"])
def test_real_gate_is_required_before_activation(setup, monkeypatch, gate):
    s = setup
    if gate == "probe":

        def fail(*_):
            raise SandboxUnavailable()

        monkeypatch.setattr(domain, "require_execution_ready", fail)
    elif gate == "fingerprint":
        monkeypatch.setattr(domain, "fingerprint", lambda *_: "f" * 64)
    else:
        s.executor.settings.runner_node_id = uuid4()
    with pytest.raises(SandboxUnavailable), scope(s):
        pytest.fail("Unverified worker")
    assert state(s)[0] == "reserved"


@pytest.mark.parametrize("foreign", ["node", "scope"])
def test_recovery_cannot_touch_foreign_node_or_scope(setup, monkeypatch, foreign):
    s = setup
    if foreign == "node":
        assert not domain.recover_one(s.engine, uuid4(), s.executor)
    else:
        monkeypatch.setattr(s.executor, "cleanup_scope", lambda: "f" * 64)
        assert not domain.recover_one(s.engine, s.node, s.executor)
    assert state(s)[0] == "reserved"


def test_cleanup_failure_stays_retryable_and_blocks_late_scope(setup, monkeypatch):
    s = setup
    original = s.executor.cleanup_attempt
    monkeypatch.setattr(s.executor, "cleanup_attempt", Mock(side_effect=CleanupUnconfirmed()))
    with pytest.raises(CleanupUnconfirmed):
        domain.recover_one(s.engine, s.node, s.executor)
    assert state(s)[0] == "cleaning"
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Late worker during cleanup")
    monkeypatch.setattr(s.executor, "cleanup_attempt", original)
    assert domain.recover_one(s.engine, s.node, s.executor)


def test_delete_erases_private_plan_and_waits_for_actual_cleanup(setup):
    s = setup
    root, _ = s.executor.attempt_paths(s.attempt)
    root.mkdir()
    (root / "private.py").write_text("synthetic source")
    remove(s)
    with Session(s.engine) as session:
        subject = session.get(RunnerSubject, str(s.owner))
        assert subject.blocked and subject.deletion_status == "restricted"
        assert session.get(domain.ValidationBatch, str(s.plan.validation_id)).plan is None
    assert root.exists()
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Deleted owner")
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert not root.exists() and state(s) == (None, None)
    with Session(s.engine) as session:
        assert session.get(RunnerSubject, str(s.owner)).deletion_status == "deleted"
    with pytest.raises(HTTPException):
        domain.register(s.engine, s.owner, s.access, s.suite, s.plan)


def test_delete_during_remote_admission_closes_activation(setup):
    s = setup
    s.admission.check.side_effect = lambda *_: remove(s)
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Late admission")
    assert state(s) == ("reserved", "withdrawn")
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert state(s) == (None, None)


def test_final_ack_failure_rolls_back_confirmation_and_retries_cleanup(setup, monkeypatch):
    import reverse_hr.services.code_runner.domain.code_runner as runner

    s = setup
    remove(s)
    original = runner.enqueue
    monkeypatch.setattr(runner, "enqueue", Mock(side_effect=HTTPException(503)))
    with pytest.raises(HTTPException):
        domain.recover_one(s.engine, s.node, s.executor)
    assert state(s)[0] == "cleaning"
    with Session(s.engine) as session:
        assert session.get(RunnerSubject, str(s.owner)).deletion_status == "restricted"
    monkeypatch.setattr(runner, "enqueue", original)
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert state(s) == (None, None)


@pytest.mark.parametrize("field", ["owner", "ordinal", "plan"])
def test_changed_binding_during_admission_closes_activation(setup, field):
    s = setup

    def tamper(*_):
        with Session(s.engine) as session, session.begin():
            if field == "plan":
                batch = session.get(domain.ValidationBatch, str(s.plan.validation_id))
                changed = dict(batch.plan)
                changed["validation_id"] = str(uuid4())
                batch.plan = changed
            else:
                attempt = session.get(domain.ValidationAttempt, str(s.attempt))
                if field == "owner":
                    attempt.owner_id = str(uuid4())
                else:
                    attempt.ordinal = 999

    s.admission.check.side_effect = tamper
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Changed binding")
    assert state(s)[0] == "reserved"


def test_foreign_owner_and_conflicting_registration_are_closed(setup):
    s = setup
    with pytest.raises(HTTPException):
        domain.register(s.engine, uuid4(), s.access, s.suite, s.plan)
    with pytest.raises(HTTPException):
        domain.reserve(s.engine, uuid4(), s.plan.validation_id, s.access, s.node, s.executor)
    changed = s.plan.model_copy(deep=True)
    changed.inputs.reverse()
    with pytest.raises(HTTPException):
        domain.register(s.engine, s.owner, s.access, s.suite, changed)
    assert state(s)[0] == "reserved"


def test_downgrade_preserves_ledger_and_readiness(setup):
    s = setup
    with pytest.raises(RuntimeError, match="cleanup obligations"):
        command.downgrade(migration_config(s.target.app.state.settings), "0006_control")
    assert s.target.client.get("/health/ready").status_code == 200


def test_empty_migration_and_diagnostic_mode_conflict(service, tmp_path, monkeypatch):
    target = service("code-runner")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0006_control")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200
    with Session(target.app.state.engine) as session, session.begin():
        require_runner_mode(session, "diagnostic")
    suite, _, plan, _ = harness_setup.__wrapped__()
    owner = uuid4()
    access = target.app.state.processing_access
    domain.register(target.app.state.engine, owner, access, suite, plan)
    executor = Mock(cleanup_scope=Mock(return_value="a" * 64))
    with pytest.raises(HTTPException):
        domain.reserve(
            target.app.state.engine, owner, plan.validation_id, access, uuid4(), executor
        )
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(domain.ValidationAttempt)) is None


@pytest.mark.parametrize("value", [False, True, {"allowed": True}])
def test_admission_must_follow_raise_on_denial_contract(setup, value):
    s = setup
    s.admission.check.return_value = value
    with pytest.raises(HTTPException), scope(s):
        pytest.fail("Unverified admission response")
    assert state(s)[0] == "reserved"


def test_prepared_batch_without_attempt_can_be_deleted_immediately(setup):
    s = setup
    domain.recover_one(s.engine, s.node, s.executor)
    with Session(s.engine) as session, session.begin():
        session.delete(session.get(domain.ValidationAttempt, str(s.attempt)))
    remove(s)
    assert state(s) == (None, None)
    with Session(s.engine) as session:
        assert session.get(RunnerSubject, str(s.owner)).deletion_status == "deleted"


def test_failed_initial_ack_preserves_plan_and_pending_obligation(setup, monkeypatch):
    import reverse_hr.services.code_runner.domain.code_runner as runner

    s = setup
    monkeypatch.setattr(runner, "enqueue", Mock(side_effect=HTTPException(503)))
    with pytest.raises(HTTPException):
        remove(s)
    with Session(s.engine) as session:
        assert not session.get(RunnerSubject, str(s.owner)).blocked
        assert session.get(
            domain.ValidationBatch, str(s.plan.validation_id)
        ).plan == s.plan.model_dump(mode="json")
    assert state(s)[0] == "reserved"


def test_deletion_waits_for_validation_attempts_on_all_nodes(setup):
    from reverse_hr.contracts.suite_validation import build_plan

    s = setup
    foreign_node = uuid4()
    second = build_plan(s.suite, s.plan.pin, uuid4())
    domain.register(s.engine, s.owner, s.access, s.suite, second)
    second_attempt = domain.reserve(
        s.engine, s.owner, second.validation_id, s.access, foreign_node, s.executor
    )
    remove(s)
    assert domain.recover_one(s.engine, s.node, s.executor)
    with Session(s.engine) as session:
        assert session.get(RunnerSubject, str(s.owner)).deletion_status == "restricted"
        assert session.get(domain.ValidationAttempt, str(second_attempt)).state == "reserved"
    assert not domain.recover_one(s.engine, s.node, s.executor)
    assert domain.recover_one(s.engine, foreign_node, s.executor)
    with Session(s.engine) as session:
        assert session.get(RunnerSubject, str(s.owner)).deletion_status == "deleted"
        assert not list(session.scalars(select(domain.ValidationAttempt)))
        assert not list(session.scalars(select(domain.ValidationBatch)))
