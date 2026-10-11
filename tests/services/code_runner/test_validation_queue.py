"""Actual signed TestClient/SQLite/OS fences with synthetic probe and executor."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import delete, event, select
from sqlalchemy.orm import Session

import reverse_hr.services.code_runner.validation_queue as domain
from reverse_hr.contracts.runner import Output
from reverse_hr.platform.migrate import migration_config
from reverse_hr.services.assessment.domain.assessment_verdicts import ValidationIntake
from reverse_hr.services.code_runner.domain.code_runner import (
    RunnerSubject,
    process_deletion_request,
)
from reverse_hr.services.code_runner.sandbox import CleanupUnconfirmed, SandboxUnavailable
from reverse_hr.services.code_runner.validation_lifecycle import (
    ValidationAttempt,
    ValidationBatch,
    ValidationCapture,
    reserve,
)
from reverse_hr.services.code_runner.validation_verdict import VerdictRecord
from reverse_hr.shared.db import Outbox
from tests.services.code_runner.test_code_runner import deletion
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture
from tests.shared.test_runtime_trust import setup as trust_setup

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch):
    s = trust_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    # Reuse actual signed catalogue/RPC clients, start a new synthetic execution queue.
    with Session(s.engine) as session, session.begin():
        for model in (VerdictRecord, ValidationCapture, ValidationAttempt, ValidationBatch, Outbox):
            session.execute(delete(model))
    monkeypatch.setattr(domain, "require_execution_ready", lambda *_: None)
    monkeypatch.setattr(domain, "fingerprint", lambda *_: s.plan.pin.runtime_fingerprint)

    def execute(kind, manifest, *, attempt_id, stop_check):
        assert stop_check() is None
        with Session(s.engine) as session:
            item = s.plan.inputs[session.get(ValidationAttempt, str(attempt_id)).ordinal]
        case = next(c for c in s.definition.cases if c.key == item.case_key)
        return (
            Output(
                status="executed",
                exit_code=0,
                stdout=case.expected_stdout,
                stderr=case.expected_stderr,
            )
            if item.source_kind == "reference"
            else Output(status="runtime_error", exit_code=1)
        )

    s.executor.execute = Mock(side_effect=execute)
    enqueue(s)
    return s


def enqueue(s, **kwargs):
    return domain.enqueue_validation(
        s.engine, s.owner, s.plan, s.processing, s.access, s.executor, **kwargs
    )


def tick(s):
    return domain.run_one(
        s.engine, s.processing, s.access, s.delivery, s.executor, s.signatures["code-runner"]
    )


def work(s):
    with Session(s.engine) as session:
        return session.get(domain.ValidationWork, str(s.plan.validation_id))


def due(s):
    with Session(s.engine) as session, session.begin():
        session.get(domain.ValidationWork, str(s.plan.validation_id)).next_run_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)


def before_delivery(s):
    for _ in range(len(s.plan.inputs) + 2):
        assert tick(s)
    assert work(s).attestation is not None and work(s).status == "pending"


def test_full_sequential_queue_signed_delivery_once(setup):
    s = setup
    assert enqueue(s) == s.plan.validation_id
    before_delivery(s)
    assert s.executor.execute.call_count == len(s.plan.inputs)
    assert tick(s) and work(s).status == "done"
    assert not tick(s)
    with Session(s.assessment.app.state.engine) as session:
        row = session.get(ValidationIntake, str(s.plan.validation_id))
        assert row.attestation is not None and row.proof["verdict"] == "accepted"
    assert not work(s).receipt["scoring_enabled"] and not work(s).receipt["runtime_validated"]
    with Session(s.engine) as session:
        events = session.scalars(select(Outbox)).all()
        event = next(e for e in events if "delivery_confirmed" in e.envelope["event_type"])
        assert event.envelope["aggregate_version"] == 3
        assert set(event.envelope["payload"]) == {"candidate_id", "validation_id"}


def test_lost_delivery_response_retries_same_report_without_execution(setup):
    s = setup
    before_delivery(s)
    original = work(s).attestation
    send = s.delivery.send_verdict

    def lost(raw, signature):
        send(raw, signature)
        raise TimeoutError("sensitive diagnostic")

    s.delivery.send_verdict = lost
    assert tick(s) and work(s).status == "pending" and work(s).failures == 1
    assert not tick(s)
    s.delivery.send_verdict = send
    due(s)
    assert tick(s) and work(s).status == "done" and work(s).attestation == original
    assert s.executor.execute.call_count == len(s.plan.inputs)
    with Session(s.assessment.app.state.engine) as session:
        assert len(session.scalars(select(ValidationIntake)).all()) == 1


def test_retry_budget_and_explicit_retry(setup, monkeypatch):
    s = setup
    monkeypatch.setattr(domain, "require_execution_ready", Mock(side_effect=SandboxUnavailable()))
    for _ in range(5):
        due(s)
        assert tick(s)
    row = work(s)
    assert row.status == "needs_attention" and row.failures == 5
    assert row.error_code == "runtime_unavailable" and not tick(s)
    assert s.executor.execute.call_count == 0
    monkeypatch.setattr(domain, "require_execution_ready", lambda *_: None)
    assert enqueue(s, retry=True) == s.plan.validation_id
    assert work(s).failures == 0 and tick(s)
    with pytest.raises(HTTPException):
        enqueue(s, retry=True)


def test_crash_reserved_attempt_cleanup_only_never_reexecutes(setup):
    s = setup
    attempt = reserve(s.engine, s.owner, s.plan.validation_id, s.processing, s.node, s.executor)
    assert tick(s) and work(s).status == "stopped"
    assert s.executor.execute.call_count == 0
    with Session(s.engine) as session:
        assert session.get(ValidationAttempt, str(attempt)).state == "cleaned"
        assert session.get(ValidationBatch, str(s.plan.validation_id)).status == "interrupted"
    with pytest.raises(HTTPException):
        enqueue(s, retry=True)


def test_batch_fence_blocks_second_worker(setup):
    s = setup
    with s.executor.attempt_guard(domain.guard_id(s.plan.validation_id)):
        with pytest.raises(CleanupUnconfirmed):
            tick(s)
    assert s.executor.execute.call_count == 0 and work(s).failures == 0
    assert tick(s)


def test_unconfirmed_cleanup_recovered_without_reexecution(setup):
    s = setup
    s.executor.execute = Mock(side_effect=CleanupUnconfirmed())
    assert tick(s) and work(s).error_code == "cleanup_unconfirmed"
    due(s)
    assert tick(s) and work(s).status == "stopped"
    assert s.executor.execute.call_count == 1
    with Session(s.engine) as session:
        assert all(a.state == "cleaned" for a in session.scalars(select(ValidationAttempt)))
        assert not session.scalars(select(ValidationCapture)).all()


def test_rejected_suite_delivered_without_candidate_score(setup):
    s = setup
    s.executor.execute = Mock(return_value=Output(status="runtime_error", exit_code=1))
    before_delivery(s)
    assert tick(s) and work(s).receipt["verdict"] == "rejected"
    assert not work(s).receipt["scoring_enabled"]


def test_corrupted_attestation_never_gets_delivery_ack(setup):
    s = setup
    before_delivery(s)
    with Session(s.engine) as session, session.begin():
        session.get(
            domain.ValidationWork, str(s.plan.validation_id)
        ).attestation_signature = "invalid"
    assert tick(s) and work(s).status == "pending" and work(s).receipt is None
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(ValidationIntake, str(s.plan.validation_id)) is None


def test_enqueue_rolls_back_batch_if_work_insert_fails(setup):
    s = setup
    new = s.plan.model_copy(update={"validation_id": uuid4()})

    def fail(*_):
        raise RuntimeError("synthetic insert failure")

    event.listen(domain.ValidationWork, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError):
            domain.enqueue_validation(s.engine, s.owner, new, s.processing, s.access, s.executor)
    finally:
        event.remove(domain.ValidationWork, "before_insert", fail)
    with Session(s.engine) as session:
        assert session.get(ValidationBatch, str(new.validation_id)) is None


@pytest.mark.parametrize("change", ["node", "scope"])
def test_foreign_assignment_not_consumed(setup, change):
    s = setup
    with Session(s.engine) as session, session.begin():
        row = session.get(domain.ValidationWork, str(s.plan.validation_id))
        if change == "node":
            row.node_id = str(uuid4())
        else:
            row.scope_id = "f" * 64
    assert not tick(s) and s.executor.execute.call_count == 0
    with pytest.raises(HTTPException):
        enqueue(s)


def test_retired_suite_stops_and_keeps_cleanup_obligation(setup):
    s = setup
    assert (
        s.assessment.client.post(
            f"/v1/test-suites/{s.plan.pin.suite_id}/retire",
            headers=headers(s.reviewer, "retire", 2),
            json={"reason": "withdrawn"},
        ).status_code
        == 200
    )
    assert tick(s) and work(s).status == "stopped"
    assert s.executor.execute.call_count == 0
    assert tick(s)  # terminal-work orphan cleanup
    with Session(s.engine) as session:
        assert all(a.state == "cleaned" for a in session.scalars(select(ValidationAttempt)))


def test_inconclusive_does_not_finalize_or_deliver(setup):
    s = setup
    s.executor.execute = Mock(
        return_value=Output(status="technical_error", reason="sandbox_failed")
    )
    assert tick(s) and tick(s) and work(s).status == "stopped"
    assert not tick(s)
    with Session(s.engine) as session:
        assert session.get(VerdictRecord, str(s.plan.validation_id)) is None
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(ValidationIntake, str(s.plan.validation_id)) is None


@pytest.mark.parametrize("when", ["pending", "reserved", "delivered"])
def test_deletion_purges_work_and_waits_for_physical_cleanup(setup, when):
    s = setup
    if when == "reserved":
        reserve(s.engine, s.owner, s.plan.validation_id, s.processing, s.node, s.executor)
    elif when == "delivered":
        before_delivery(s)
        assert tick(s)
    with Session(s.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.owner))
    assert work(s) is None
    if when == "reserved":
        with Session(s.engine) as session:
            assert session.get(RunnerSubject, str(s.owner)).deletion_status == "restricted"
        assert tick(s)  # own-node orphan recovery works without queue private material
    with Session(s.engine) as session:
        assert session.get(RunnerSubject, str(s.owner)).deletion_status == "deleted"
        assert not [
            e
            for e in session.scalars(select(Outbox))
            if "delivery_confirmed" in e.envelope["event_type"]
        ]
    assert not tick(s)


def test_final_delivery_delete_does_not_publish_late_ack(setup):
    s = setup
    before_delivery(s)
    send = s.delivery.send_verdict

    def deleted(raw, signature):
        reply = send(raw, signature)
        with Session(s.engine) as session, session.begin():
            process_deletion_request(session, deletion(s.owner))
        return reply

    s.delivery.send_verdict = deleted
    assert tick(s) and work(s) is None
    with Session(s.engine) as session:
        assert not [
            e
            for e in session.scalars(select(Outbox))
            if "delivery_confirmed" in e.envelope["event_type"]
        ]


def test_delivery_outbox_failure_rolls_back_done_and_replay_is_safe(setup, monkeypatch):
    s = setup
    before_delivery(s)
    emit = domain.emit
    monkeypatch.setattr(domain, "emit", Mock(side_effect=RuntimeError("sensitive")))
    assert tick(s) and work(s).status == "pending" and work(s).receipt is None
    monkeypatch.setattr(domain, "emit", emit)
    due(s)
    assert tick(s) and work(s).status == "done"
    assert s.executor.execute.call_count == len(s.plan.inputs)


def test_trusted_plan_and_local_fingerprint_required_before_enqueue(setup, monkeypatch):
    s = setup
    with Session(s.engine) as session, session.begin():
        session.delete(session.get(domain.ValidationWork, str(s.plan.validation_id)))
    monkeypatch.setattr(domain, "fingerprint", lambda *_: "f" * 64)
    with pytest.raises(SandboxUnavailable):
        enqueue(s)
    assert work(s) is None
    monkeypatch.setattr(domain, "fingerprint", lambda *_: s.plan.pin.runtime_fingerprint)
    s.access.fetch = Mock(side_effect=HTTPException(503))
    with pytest.raises(HTTPException):
        enqueue(s)
    assert work(s) is None


def test_populated_downgrade_keeps_readiness(setup):
    s = setup
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.runner.app.state.settings), "0009_verdicts")
    assert s.runner.client.get("/health/ready").status_code == 200


def test_empty_queue_migration_roundtrip(service):
    s = service("code-runner")
    config = migration_config(s.app.state.settings)
    command.downgrade(config, "0009_verdicts")
    assert s.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert s.client.get("/health/ready").status_code == 200
