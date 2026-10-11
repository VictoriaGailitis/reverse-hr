"""Fenced execution lifecycle with synthetic executor outputs; no real Linux run."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

import reverse_hr.services.code_runner.validation_lifecycle as domain
from reverse_hr.contracts.runner import Output
from reverse_hr.contracts.suite_validation import compare_bound_captures
from reverse_hr.platform.migrate import migration_config
from reverse_hr.services.code_runner.sandbox import CleanupUnconfirmed
from reverse_hr.shared.db import Outbox
from tests.services.code_runner.test_validation_lifecycle import remove, state
from tests.services.code_runner.test_validation_lifecycle import setup as lifecycle_setup


@pytest.fixture
def setup(service, tmp_path, monkeypatch):
    s = lifecycle_setup.__wrapped__(service, tmp_path, monkeypatch)
    outputs = {case.key: case for case in s.suite.cases}

    def execute(kind, manifest, *, attempt_id, stop_check):
        assert kind == s.plan.format
        assert stop_check() is None
        with Session(s.engine) as session:
            attempt = session.get(domain.ValidationAttempt, str(attempt_id))
            assert attempt.state == "active"
            item = s.plan.inputs[attempt.ordinal]
            assert manifest == item.manifest.model_dump(mode="json")
        expected = outputs[item.case_key]
        return (
            Output(
                status="executed",
                exit_code=0,
                stdout=expected.expected_stdout,
                stderr=expected.expected_stderr,
            )
            if item.source_kind == "reference"
            else Output(status="runtime_error", exit_code=1)
        )

    s.executor.execute = Mock(side_effect=execute)
    return s


def execute(s):
    return domain.execute_reserved(s.engine, s.access, s.admission, s.node, s.attempt, s.executor)


def captures(s):
    from reverse_hr.contracts.suite_validation import CaseCapture

    with Session(s.engine) as session:
        return [
            CaseCapture.model_validate(row.capture)
            for row in session.scalars(select(domain.ValidationCapture))
        ]


def test_complete_sequence_preserves_each_attempt_and_bound_capture(setup):
    s = setup
    for ordinal, item in enumerate(s.plan.inputs):
        capture = execute(s)
        assert capture.source_kind == item.source_kind and capture.case_key == item.case_key
        assert capture.manifest_digest == item.manifest_digest
        assert state(s)[0] == "cleaned"
        if ordinal < len(s.plan.inputs) - 1:
            assert state(s)[1] == "prepared"
            s.attempt = domain.reserve(
                s.engine, s.owner, s.plan.validation_id, s.access, s.node, s.executor
            )
            assert s.attempt
            assert (
                domain.reserve(
                    s.engine, s.owner, s.plan.validation_id, s.access, s.node, s.executor
                )
                is None
            )
    assert state(s)[1] == "captures_ready"
    assert len(captures(s)) == len(s.plan.inputs)
    assert compare_bound_captures(s.suite, s.plan, captures(s)) == "accepted"
    assert not domain.recover_one(s.engine, s.node, s.executor)
    with pytest.raises(HTTPException):
        domain.reserve(s.engine, s.owner, s.plan.validation_id, s.access, s.node, s.executor)
    with Session(s.engine) as session:
        events = session.scalars(select(Outbox)).all()
        assert len(events) == 1
        assert events[0].envelope["event_type"] == "code-runner.validation_captures_ready.v1"
        assert set(events[0].envelope["payload"]) == {"candidate_id", "validation_id"}
    assert s.executor.execute.call_count == len(s.plan.inputs)


@pytest.mark.parametrize(
    "output",
    [
        Output(status="technical_error", reason="sandbox_failed"),
        Output(status="cancelled", reason="access_withdrawn"),
        Output(status="limit_exceeded", reason="time_limit"),
    ],
)
def test_uncertain_output_stops_batch_without_zero_or_success(setup, output):
    s = setup
    s.executor.execute.side_effect = lambda *_args, **_kwargs: output
    assert execute(s).output.status == output.status
    assert state(s) == ("cleaned", "inconclusive")
    with pytest.raises(HTTPException):
        domain.reserve(s.engine, s.owner, s.plan.validation_id, s.access, s.node, s.executor)
    assert len(captures(s)) == 1


def test_unexpected_executor_failure_is_redacted_and_cleaned(setup):
    s = setup
    s.executor.execute.side_effect = RuntimeError("Synthetic failure containing sensitive text")
    result = execute(s)
    assert result.output == Output(status="technical_error", reason="sandbox_failed")
    assert state(s) == ("cleaned", "inconclusive")


@pytest.mark.parametrize("failure", ["executor_cleanup", "confirmation_cleanup"])
def test_no_output_is_published_before_confirmed_cleanup(setup, monkeypatch, failure):
    s = setup
    if failure == "executor_cleanup":
        s.executor.execute.side_effect = CleanupUnconfirmed()
    else:
        monkeypatch.setattr(s.executor, "cleanup_attempt", Mock(side_effect=CleanupUnconfirmed()))
    with pytest.raises(CleanupUnconfirmed):
        execute(s)
    assert state(s) == ("active", "prepared")
    assert not captures(s)
    monkeypatch.setattr(s.executor, "cleanup_attempt", lambda *_: None)
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert state(s) == ("cleaned", "interrupted")
    assert not captures(s)


def test_deletion_during_execute_purges_output_and_waits_for_cleanup(setup):
    s = setup

    def deleted(*_, **__):
        remove(s)
        return Output(status="executed", exit_code=0, stdout="must not publish")

    s.executor.execute.side_effect = deleted
    assert execute(s) is None
    assert state(s) == (None, None) and not captures(s)


@pytest.mark.parametrize("failure", [409, 503])
def test_permission_lost_after_execute_overrides_success(setup, failure):
    s = setup

    def revoked(*_, **__):
        s.access.check = Mock(side_effect=HTTPException(failure))
        return Output(status="executed", exit_code=0, stdout="must redact")

    s.executor.execute.side_effect = revoked
    result = execute(s)
    assert result.output.stdout == ""
    assert result.output.status == ("cancelled" if failure == 409 else "technical_error")
    assert state(s) == ("cleaned", "inconclusive")


def test_final_outbox_failure_preserves_obligation_but_never_reexecutes(setup, monkeypatch):
    import reverse_hr.shared.db as db

    s = setup
    s.executor.execute.side_effect = lambda *_, **__: Output(
        status="technical_error", reason="sandbox_failed"
    )
    monkeypatch.setattr(db, "enqueue", Mock(side_effect=HTTPException(503)))
    with pytest.raises(HTTPException):
        execute(s)
    assert state(s) == ("active", "prepared")
    assert not captures(s)
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert state(s) == ("cleaned", "interrupted")
    assert s.executor.execute.call_count == 1


@pytest.mark.parametrize("change", ["input", "attempt", "missing", "status"])
def test_corrupted_previous_capture_blocks_next_reservation(setup, change):
    s = setup
    execute(s)
    with Session(s.engine) as session, session.begin():
        row = session.get(domain.ValidationCapture, str(s.attempt))
        if change == "missing":
            session.delete(row)
        else:
            data = dict(row.capture)
            if change == "input":
                data["manifest_digest"] = "f" * 64
            elif change == "attempt":
                data["attempt_id"] = str(uuid4())
            else:
                data["output"] = Output(
                    status="technical_error", reason="sandbox_failed"
                ).model_dump(mode="json")
            row.capture = data
    with pytest.raises(HTTPException):
        domain.reserve(s.engine, s.owner, s.plan.validation_id, s.access, s.node, s.executor)
    assert s.executor.execute.call_count == 1


def test_captures_deletion_and_protected_downgrade(setup):
    s = setup
    execute(s)
    with pytest.raises(RuntimeError, match="private validation captures"):
        command.downgrade(migration_config(s.target.app.state.settings), "0007_validation")
    assert s.target.client.get("/health/ready").status_code == 200
    remove(s)
    assert not captures(s) and state(s) == (None, None)


def test_stop_reason_handles_contract_denial_and_stale_local_state(setup):
    s = setup
    with domain.validation_scope(s.engine, s.access, s.admission, s.node, s.attempt, s.executor):
        assert domain.stop_reason(s.engine, s.access, s.admission, s.attempt) is None
        s.admission.check.return_value = True
        assert (
            domain.stop_reason(s.engine, s.access, s.admission, s.attempt)
            == "admission_unavailable"
        )
        s.admission.check.return_value = None
        s.admission.check.side_effect = HTTPException(409)
        assert domain.stop_reason(s.engine, s.access, s.admission, s.attempt) == "access_withdrawn"
    assert domain.recover_one(s.engine, s.node, s.executor)
    assert domain.stop_reason(s.engine, s.access, s.admission, s.attempt) == "access_withdrawn"


def test_scope_rejects_non_contiguous_valid_range_ordinal(setup):
    s = setup
    with Session(s.engine) as session, session.begin():
        session.get(domain.ValidationAttempt, str(s.attempt)).ordinal = 2
    with pytest.raises(HTTPException):
        execute(s)
    assert not s.executor.execute.called


def test_latched_stop_during_final_processing_check_redacts_capture(setup, monkeypatch):
    import reverse_hr.services.code_runner.runner_monitor as monitoring

    s = setup
    latched = [None]

    class Monitor:
        def __init__(self, *_):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def current(self):
            return latched[0]

    monkeypatch.setattr(monitoring, "StopMonitor", Monitor)

    def outcome(*_, **__):
        count = [0]

        def check(*_):
            count[0] += 1
            # First is final stop_reason, second is publication guard.
            if count[0] == 2:
                latched[0] = "access_withdrawn"

        s.access.check = check
        return Output(status="executed", exit_code=0, stdout="must redact")

    s.executor.execute.side_effect = outcome
    result = execute(s)
    assert result.output == Output(status="cancelled", reason="access_withdrawn")
    assert state(s) == ("cleaned", "inconclusive")


def test_empty_capture_migration_roundtrip(service):
    target = service("code-runner")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0007_validation")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200
