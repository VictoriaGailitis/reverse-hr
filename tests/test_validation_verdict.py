"""Actual signed trusted material and verdict; executor/probe remain synthetic."""

from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_event_transport import signatures as signatures_fixture
from test_suite_admission import setup as admission_setup

import reverse_hr.runner_monitor as monitoring
import reverse_hr.validation_lifecycle as lifecycle
import reverse_hr.validation_verdict as domain
from reverse_hr.db import Outbox
from reverse_hr.domains.code_runner import Output, process_deletion_request
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import canonical, sign, verify
from reverse_hr.sandbox import NsjailExecutor, SandboxUnavailable
from reverse_hr.settings import Settings
from reverse_hr.suite_admission import (
    MATERIAL_REQUEST,
    MATERIAL_RESPONSE,
    SuiteMaterial,
    SuiteMaterialRequest,
)

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch):
    class DrainedMonitor(monitoring.StopMonitor):
        def __exit__(self, *args):
            result = super().__exit__(*args)
            # Synthetic executions finish instantly; drain their real signed RPC
            # before starting the next case or tearing down its service databases.
            if self.thread:
                self.thread.join(timeout=5)
                assert not self.thread.is_alive(), "signed admission check did not finish"
            return result

    monkeypatch.setattr(monitoring, "StopMonitor", DrainedMonitor)
    s = admission_setup.__wrapped__(service, token, signatures)
    s.engine, s.processing = s.runner.app.state.engine, s.runner.app.state.processing_access
    scratch, groups = tmp_path / "scratch", tmp_path / "groups"
    scratch.mkdir(mode=0o700)
    groups.mkdir()
    s.node = uuid4()
    s.executor = NsjailExecutor(
        Settings(
            service_name="code-runner",
            runner_node_id=s.node,
            runner_scratch=str(scratch),
            runner_cgroup_parent=str(groups),
        )
    )
    monkeypatch.setattr(s.executor, "validate", lambda: None)
    for module in (lifecycle, domain):
        monkeypatch.setattr(module, "require_execution_ready", lambda *_: None)
        monkeypatch.setattr(module, "fingerprint", lambda *_: s.plan.pin.runtime_fingerprint)

    def send(raw, signature):
        response = s.assessment.client.post(
            "/internal/v1/suite-validation-material",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise ValueError(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    s.send_material = s.access.send_material = send
    lifecycle.register(s.engine, s.owner, s.processing, s.definition, s.plan)
    for item in s.plan.inputs:
        attempt = lifecycle.reserve(
            s.engine, s.owner, s.plan.validation_id, s.processing, s.node, s.executor
        )
        case = next(case for case in s.definition.cases if case.key == item.case_key)
        output = (
            Output(
                status="executed",
                exit_code=0,
                stdout=case.expected_stdout,
                stderr=case.expected_stderr,
            )
            if item.source_kind == "reference"
            else Output(status="runtime_error", exit_code=1)
        )
        s.executor.execute = Mock(return_value=output)
        assert lifecycle.execute_reserved(
            s.engine, s.processing, s.access, s.node, attempt, s.executor
        )
    return s


def finish(s, owner=None):
    return domain.finalize(
        s.engine,
        owner or s.owner,
        s.plan.validation_id,
        s.processing,
        s.access,
        s.executor,
        s.signatures["code-runner"],
    )


def rows(s, model):
    with Session(s.engine) as session:
        return session.scalars(select(model)).all()


def test_fresh_material_full_matrix_verdict_signed_atomic_and_idempotent(setup):
    s = setup
    assert s.access.fetch(s.owner, s.plan) == s.definition
    proof, signature = finish(s)
    assert proof.verdict == "accepted" and proof.demo and not proof.scoring_enabled
    verify(s.signatures["assessment"], "code-runner", signature, domain.VERDICT_CONTEXT, proof)
    assert finish(s) == (proof, signature)
    assert len(rows(s, domain.VerdictRecord)) == 1
    assert proof.captures_count == len(s.plan.inputs)
    assert (
        "expected_stdout" not in canonical(proof).decode()
        and "main.py" not in canonical(proof).decode()
    )
    events = rows(s, Outbox)
    assert len(events) == 2 and events[-1].envelope["aggregate_version"] == 2
    assert set(events[-1].envelope["payload"]) == {"candidate_id", "validation_id"}


@pytest.mark.parametrize("failure", ["reference", "mutant"])
def test_reference_failure_or_surviving_mutant_rejects_suite(setup, failure):
    s = setup
    with Session(s.engine) as session, session.begin():
        captures = session.scalars(select(lifecycle.ValidationCapture)).all()
        for row in captures:
            data = dict(row.capture)
            if (failure == "reference" and data["source_kind"] == "reference") or (
                failure == "mutant" and data["source_kind"] == "mutant"
            ):
                data["output"] = Output(
                    status="executed",
                    exit_code=0,
                    stdout="wrong"
                    if failure == "reference"
                    else s.definition.cases[0].expected_stdout,
                ).model_dump(mode="json")
                row.capture = data
    assert finish(s)[0].verdict == "rejected"


@pytest.mark.parametrize("retire", ["suite", "content"])
def test_replay_needs_current_trusted_material(setup, retire):
    s = setup
    finish(s)
    path = (
        f"/v1/test-suites/{s.plan.pin.suite_id}/retire"
        if retire == "suite"
        else f"/v1/content-versions/{s.plan.pin.revision_id}/retire"
    )
    assert (
        s.assessment.client.post(
            path, headers=headers(s.reviewer, "withdraw", 2), json={"reason": "Withdrawal"}
        ).status_code
        == 200
    )
    with pytest.raises(HTTPException) as exc:
        finish(s)
    assert exc.value.status_code == 409
    assert len(rows(s, domain.VerdictRecord)) == 1


@pytest.mark.parametrize("change", ["missing", "capture", "node", "scope", "uncleaned"])
def test_no_verdict_for_incomplete_corrupted_or_unconfirmed_matrix(setup, change):
    s = setup
    with Session(s.engine) as session, session.begin():
        attempt = session.scalar(select(lifecycle.ValidationAttempt))
        if change == "missing":
            session.delete(session.get(lifecycle.ValidationCapture, attempt.attempt_id))
        elif change == "capture":
            row = session.get(lifecycle.ValidationCapture, attempt.attempt_id)
            data = dict(row.capture)
            data["manifest_digest"] = "f" * 64
            row.capture = data
        elif change == "node":
            attempt.node_id = str(uuid4())
        elif change == "scope":
            attempt.scope_id = "f" * 64
        else:
            attempt.state = "active"
    with pytest.raises(HTTPException):
        finish(s)
    assert not rows(s, domain.VerdictRecord)


@pytest.mark.parametrize(
    "failure", ["material", "probe", "fingerprint", "processing", "signing", "outbox"]
)
def test_failure_never_issues_success_or_zero(setup, monkeypatch, failure):
    s = setup
    if failure == "material":
        s.access.send_material = Mock(side_effect=TimeoutError())
    elif failure == "probe":
        monkeypatch.setattr(
            domain, "require_execution_ready", Mock(side_effect=SandboxUnavailable())
        )
    elif failure == "fingerprint":
        monkeypatch.setattr(domain, "fingerprint", lambda *_: "f" * 64)
    elif failure == "processing":
        s.processing.check = Mock(side_effect=HTTPException(503))
    else:
        monkeypatch.setattr(
            domain,
            "sign" if failure == "signing" else "enqueue",
            Mock(side_effect=HTTPException(503)),
        )
    with pytest.raises((HTTPException, SandboxUnavailable)):
        finish(s)
    assert not rows(s, domain.VerdictRecord)
    assert len(rows(s, Outbox)) == 1
    assert rows(s, lifecycle.ValidationBatch)[0].status == "captures_ready"


@pytest.mark.parametrize("change", ["signature", "proof", "owner", "batch"])
def test_corrupted_stored_verdict_cannot_be_replayed(setup, change):
    s = setup
    finish(s)
    with Session(s.engine) as session, session.begin():
        row = session.get(domain.VerdictRecord, str(s.plan.validation_id))
        if change == "signature":
            row.signature = "invalid"
        elif change == "owner":
            row.owner_id = str(uuid4())
        elif change == "batch":
            session.get(lifecycle.ValidationBatch, str(s.plan.validation_id)).status = "rejected"
        else:
            row.proof = dict(row.proof) | {"captures_digest": "f" * 64}
    with pytest.raises(HTTPException) as exc:
        finish(s)
    assert exc.value.status_code == 409


def test_deletion_during_material_fetch_and_final_processing_closes_commit(setup):
    from test_code_runner import deletion

    s = setup
    original = s.access.fetch

    def removed(*args):
        definition = original(*args)
        with Session(s.engine) as session, session.begin():
            process_deletion_request(session, deletion(s.owner))
        return definition

    s.access.fetch = removed
    with pytest.raises(HTTPException):
        finish(s)
    assert not rows(s, domain.VerdictRecord) and not rows(s, lifecycle.ValidationCapture)


def test_signed_verdict_deletion_and_guarded_downgrade(setup):
    from test_code_runner import deletion

    s = setup
    finish(s)
    with pytest.raises(RuntimeError, match="signed validation verdicts"):
        command.downgrade(migration_config(s.runner.app.state.settings), "0008_captures")
    assert s.runner.client.get("/health/ready").status_code == 200
    with Session(s.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.owner))
    assert not rows(s, domain.VerdictRecord)
    assert [row.envelope["event_type"] for row in rows(s, Outbox)] == [
        "code-runner.data_deleted.v1"
    ]


def test_empty_verdict_migration_roundtrip(service):
    target = service("code-runner")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0008_captures")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("bad", ["context", "signature", "digest", "owner", "plan", "oversize"])
def test_signed_material_cannot_be_rebound_or_tampered(setup, bad):
    s = setup

    def modified(raw, signature):
        data, _ = s.send_material(raw, signature)
        receipt = SuiteMaterial.model_validate_json(data)
        if bad == "digest":
            receipt.definition.cases[0].expected_stdout = "tampered answer"
        elif bad == "owner":
            receipt.candidate_id = uuid4()
        elif bad == "plan":
            receipt.plan_digest = "f" * 64
        raw = canonical(receipt) + (b" " * 2101248 if bad == "oversize" else b"")
        sig = sign(
            s.signatures["assessment"],
            MATERIAL_REQUEST if bad == "context" else MATERIAL_RESPONSE,
            receipt,
        )
        return raw, "invalid" if bad == "signature" else sig

    s.access.send_material = modified
    with pytest.raises(HTTPException) as exc:
        s.access.fetch(s.owner, s.plan)
    assert exc.value.status_code == 503


def test_material_request_replay_and_cross_context_denied(setup):
    from datetime import UTC, datetime

    s = setup
    body = SuiteMaterialRequest(
        candidate_id=s.owner,
        requester="code-runner",
        purpose="suite-validation-material",
        validation_id=s.plan.validation_id,
        pin=s.plan.pin,
        plan_digest=domain.digest(s.plan),
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )
    raw, signature = canonical(body), sign(s.signatures["code-runner"], MATERIAL_REQUEST, body)
    assert s.send_material(raw, signature)
    with pytest.raises(ValueError):
        s.send_material(raw, signature)
    with pytest.raises(ValueError):
        s.send_material(
            canonical(body.model_copy(update={"nonce": uuid4()})),
            sign(s.signatures["code-runner"], MATERIAL_RESPONSE, body),
        )


def test_final_processing_revocation_and_changed_matrix_close_verdict(setup):
    s = setup
    original = s.access.fetch

    def revoked(*args):
        definition = original(*args)
        s.processing.check = Mock(side_effect=HTTPException(409))
        return definition

    s.access.fetch = revoked
    with pytest.raises(HTTPException) as exc:
        finish(s)
    assert exc.value.status_code == 409
    assert not rows(s, domain.VerdictRecord)


def test_changed_capture_during_material_rpc_is_rejected(setup):
    s = setup
    original = s.access.fetch

    def changed(*args):
        definition = original(*args)
        with Session(s.engine) as session, session.begin():
            row = session.scalar(select(lifecycle.ValidationCapture))
            data = dict(row.capture)
            data["output"] = Output(status="runtime_error", exit_code=1).model_dump(mode="json")
            row.capture = data
        return definition

    s.access.fetch = changed
    with pytest.raises(HTTPException) as exc:
        finish(s)
    assert exc.value.status_code == 409
    assert not rows(s, domain.VerdictRecord)


def test_foreign_owner_and_wrong_signing_key_cannot_issue_verdict(setup):
    s = setup
    with pytest.raises(HTTPException) as exc:
        finish(s, uuid4())
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        domain.finalize(
            s.engine,
            s.owner,
            s.plan.validation_id,
            s.processing,
            s.access,
            s.executor,
            s.signatures["evaluation"],
        )
    assert exc.value.status_code == 503
    assert not rows(s, domain.VerdictRecord)
