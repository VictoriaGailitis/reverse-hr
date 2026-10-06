"""Actual signatures and SQLite; probe/execution are explicitly synthetic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy.orm import Session
from test_access import headers
from test_assessment_verdicts import body, post
from test_assessment_verdicts import setup as intake_setup
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture

import reverse_hr.validation_attestation as domain
from reverse_hr.db import Outbox
from reverse_hr.domains.assessment_sessions import process_deletion_request
from reverse_hr.domains.assessment_verdicts import ValidationIntake
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import sign, verify
from reverse_hr.runner_readiness import ProbeRecord
from reverse_hr.runtime_policy import TrustedRuntime
from reverse_hr.runtime_trust import RUNTIME_CONTEXT, check_binding, decide
from reverse_hr.sandbox import SandboxUnavailable
from reverse_hr.settings import Settings
from reverse_hr.test_suites import digest
from reverse_hr.validation_verdict import VerdictRecord

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch):
    s = intake_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    s.probe = ProbeRecord(
        node_id=s.node,
        fingerprint=s.proof.pin.runtime_fingerprint,
        checked_at=s.proof.completed_at - timedelta(minutes=1),
        passed=12,
    )
    monkeypatch.setattr(domain, "require_execution_ready", lambda *_: None)
    monkeypatch.setattr(domain, "read_record", lambda *_: s.probe)
    monkeypatch.setattr(domain, "fingerprint", lambda *_: s.probe.fingerprint)
    s.report, s.report_signature = attest(s)
    s.policy = TrustedRuntime(
        policy_id=uuid4(),
        node_id=s.node,
        fingerprint=s.probe.fingerprint,
        approved_at=s.probe.checked_at - timedelta(minutes=1),
        expires_at=s.probe.checked_at + timedelta(hours=12),
    )
    return s


def attest(s):
    return domain.attest(
        s.engine,
        s.owner,
        s.proof.validation_id,
        s.processing,
        s.access,
        s.executor,
        s.signatures["code-runner"],
    )


def deliver(s):
    return s.delivery.deliver(
        s.proof, s.proof_signature, attestation=s.report, attestation_signature=s.report_signature
    )


def status(s, auth=None):
    return s.assessment.client.get(
        f"/v1/test-suites/{s.proof.pin.suite_id}/validations/{s.proof.validation_id}/runtime-admission",
        headers=auth or s.reviewer,
    )


def test_signed_attestation_closed_default_allowlist_and_fresh_revocation(setup):
    s = setup
    verify(s.signatures["assessment"], "code-runner", s.report_signature, RUNTIME_CONTEXT, s.report)
    check_binding(s.proof, s.report)
    receipt = deliver(s)
    assert receipt.attestation_digest == digest(s.report)
    assert not receipt.scoring_enabled and not receipt.runtime_validated
    assert status(s).json()["reason"] == "policy_missing"
    s.assessment.app.state.settings.assessment_trusted_runtimes = [s.policy]
    decision = status(s).json()
    assert decision["runtime_admitted"] and decision["reason"] == "admitted"
    assert decision["policy_id"] == str(s.policy.policy_id) and not decision["scoring_enabled"]
    assert deliver(s).allowed
    s.assessment.app.state.settings.assessment_trusted_runtimes = []
    assert not status(s).json()["runtime_admitted"]


def test_late_attestation_and_fresh_signed_replay_do_not_replace_probe(setup):
    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    assert status(s).json()["reason"] == "attestation_missing"
    assert deliver(s).allowed
    original = s.report.model_dump(mode="json")
    s.report, s.report_signature = attest(s)
    assert deliver(s).allowed
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(ValidationIntake, str(s.proof.validation_id)).attestation == original
        assert (
            len(
                [
                    row
                    for row in session.query(Outbox).all()
                    if "runtime_attestation_received" in row.envelope["event_type"]
                ]
            )
            == 1
        )
    changed = s.report.model_copy(deep=True)
    changed.probe.node_id = uuid4()
    request = body(s).model_copy(
        update={
            "attestation": changed,
            "attestation_signature": sign(s.signatures["code-runner"], RUNTIME_CONTEXT, changed),
        }
    )
    assert post(s, request).status_code == 409
    with Session(s.assessment.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.owner))
    with Session(s.assessment.app.state.engine) as session:
        assert not [
            row
            for row in session.query(Outbox).all()
            if "runtime_attestation_received" in row.envelope["event_type"]
        ]


@pytest.mark.parametrize("failure", ["outbox", "signing"])
def test_late_attestation_transaction_rolls_back(setup, monkeypatch, failure):
    import reverse_hr.domains.assessment_verdicts as intake

    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    monkeypatch.setattr(
        intake, "enqueue" if failure == "outbox" else "sign", Mock(side_effect=HTTPException(503))
    )
    with pytest.raises(HTTPException):
        deliver(s)
    with Session(s.assessment.app.state.engine) as session:
        row = session.get(ValidationIntake, str(s.proof.validation_id))
        assert row.attestation is None and row.attestation_signature is None


@pytest.mark.parametrize("failure", ["delete", "revoke"])
def test_final_runner_guard_after_remote_admission(setup, failure):
    from reverse_hr.domains.code_runner import process_deletion_request as delete_runner

    s = setup

    def check(owner, plan):
        if failure == "delete":
            with Session(s.engine) as session, session.begin():
                delete_runner(session, deletion(s.owner))
        else:
            s.processing.check = Mock(side_effect=HTTPException(409))

    s.access.check = check
    with pytest.raises(HTTPException):
        attest(s)


def test_client_requires_receipt_to_bind_attestation(setup):
    from reverse_hr.processing_access import canonical
    from reverse_hr.verdict_delivery import INTAKE_RESPONSE, VerdictReceipt

    s = setup

    def altered(raw, signature):
        data, _ = s.send(raw, signature)
        receipt = VerdictReceipt.model_validate_json(data)
        receipt.attestation_digest = None
        return canonical(receipt), sign(s.signatures["assessment"], INTAKE_RESPONSE, receipt)

    s.delivery.send_verdict = altered
    with pytest.raises(HTTPException) as exc:
        deliver(s)
    assert exc.value.status_code == 503


@pytest.mark.parametrize(
    "change", ["expired", "future", "approved_after_probe", "node", "fingerprint"]
)
def test_policy_bounds_and_identity(setup, change):
    s = setup
    update = {
        "expired": {"expires_at": datetime.now(UTC) - timedelta(seconds=1)},
        "future": {"approved_at": datetime.now(UTC) + timedelta(hours=1)},
        "approved_after_probe": {"approved_at": s.probe.checked_at + timedelta(seconds=1)},
        "node": {"node_id": uuid4()},
        "fingerprint": {"fingerprint": "f" * 64},
    }[change]
    policy = s.policy.model_copy(update=update)
    result = decide(s.proof, s.report, [policy])
    assert not result.runtime_admitted and not result.scoring_enabled
    assert result.reason == (
        "policy_expired"
        if change == "expired"
        else "policy_missing"
        if change in {"node", "fingerprint"}
        else "policy_not_yet_active"
    )


def test_report_expiry_rejection_and_no_report(setup):
    s = setup
    assert decide(s.proof, None, [s.policy]).reason == "attestation_missing"
    assert decide(s.proof, s.report, [s.policy], active=False).reason == "suite_inactive"
    assert (
        decide(s.proof.model_copy(update={"verdict": "rejected"}), None, [s.policy]).reason
        == "verdict_rejected"
    )
    assert (
        decide(
            s.proof, s.report, [s.policy], now=s.probe.checked_at + timedelta(hours=24, seconds=1)
        ).reason
        == "attestation_expired"
    )


@pytest.mark.parametrize(
    "bad",
    [
        "owner",
        "batch",
        "digest",
        "fingerprint",
        "future",
        "naive",
        "late_probe",
        "stale_probe",
        "wrong_key",
        "context",
    ],
)
def test_intake_rejects_signed_but_unbound_or_unauthenticated_report(setup, bad):
    s = setup
    report = s.report.model_copy(deep=True)
    if bad == "owner":
        report.owner_id = uuid4()
    elif bad == "batch":
        report.validation_id = uuid4()
    elif bad == "digest":
        report.proof_digest = "f" * 64
    elif bad == "fingerprint":
        report.probe.fingerprint = "f" * 64
    elif bad == "future":
        report.issued_at = datetime.now(UTC) + timedelta(hours=1)
    elif bad == "naive":
        report.probe.checked_at = datetime.now()
    elif bad == "late_probe":
        report.probe.checked_at = s.proof.completed_at + timedelta(seconds=1)
    elif bad == "stale_probe":
        report.probe.checked_at = s.proof.completed_at - timedelta(hours=25)
    signed = sign(
        s.signatures["assessment" if bad == "wrong_key" else "code-runner"],
        b"other" if bad == "context" else RUNTIME_CONTEXT,
        report,
    )
    request = body(s).model_copy(update={"attestation": report, "attestation_signature": signed})
    assert post(s, request).status_code == 401
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(ValidationIntake, str(s.proof.validation_id)) is None


def test_current_retirement_processing_and_mfa(setup, token):
    s = setup
    deliver(s)
    s.assessment.app.state.settings.assessment_trusted_runtimes = [s.policy]
    assert status(s, token(roles=("candidate",))).status_code == 403
    assert status(s, token(roles=("content_admin",), amr=[])).status_code == 403
    s.assessment.app.state.processing_access.check = Mock(side_effect=HTTPException(503))
    assert status(s).status_code == 503
    s.assessment.app.state.processing_access.check = Mock()
    assert (
        s.assessment.client.post(
            f"/v1/test-suites/{s.proof.pin.suite_id}/retire",
            json={"reason": "withdrawn"},
            headers=headers(s.reviewer, "retire", 2),
        ).status_code
        == 200
    )
    assert status(s).json()["reason"] == "suite_inactive"


@pytest.mark.parametrize("bad", ["signature", "binding", "missing_signature"])
def test_corrupted_stored_attestation_fails_closed(setup, bad):
    s = setup
    deliver(s)
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(ValidationIntake, str(s.proof.validation_id))
        if bad == "signature":
            row.attestation_signature = "invalid"
        elif bad == "missing_signature":
            row.attestation_signature = None
        else:
            row.attestation = row.attestation | {"owner_id": str(uuid4())}
    assert status(s).status_code == 409


@pytest.mark.parametrize(
    "bad", ["readiness", "changed_probe", "node", "permission", "proof", "signing"]
)
def test_runner_attestation_guards(setup, monkeypatch, bad):
    s = setup
    if bad == "readiness":
        monkeypatch.setattr(
            domain, "require_execution_ready", Mock(side_effect=SandboxUnavailable())
        )
    elif bad == "changed_probe":
        monkeypatch.setattr(
            domain,
            "read_record",
            Mock(
                side_effect=[
                    s.probe,
                    s.probe.model_copy(
                        update={"checked_at": s.probe.checked_at - timedelta(seconds=1)}
                    ),
                ]
            ),
        )
    elif bad == "node":
        s.probe.node_id = uuid4()
    elif bad == "permission":
        s.access.check = Mock(side_effect=HTTPException(409))
    elif bad == "signing":
        monkeypatch.setattr(domain, "sign", Mock(side_effect=ValueError()))
    else:
        with Session(s.engine) as session, session.begin():
            session.get(VerdictRecord, str(s.proof.validation_id)).signature = "invalid"
    with pytest.raises((HTTPException, SandboxUnavailable)):
        attest(s)


def test_attestation_purge_and_protected_migration(setup):
    s = setup
    deliver(s)
    config = migration_config(s.assessment.app.state.settings)
    with pytest.raises(RuntimeError):
        command.downgrade(config, "0008_assessment")
    with Session(s.assessment.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.owner))
    assert status(s).status_code == 404
    assert s.assessment.client.get("/health/ready").status_code == 200


def test_policy_config_rejects_unbounded_naive_duplicate_entries():
    now = datetime.now(UTC)
    data = dict(
        policy_id=uuid4(),
        node_id=uuid4(),
        fingerprint="a" * 64,
        approved_at=now,
        expires_at=now + timedelta(hours=1),
    )
    for change in (
        {"expires_at": now},
        {"expires_at": now + timedelta(days=8)},
        {"approved_at": datetime.now()},
        {"fingerprint": "bad"},
    ):
        with pytest.raises(ValueError):
            TrustedRuntime(**(data | change))
    policy = TrustedRuntime(**data)
    with pytest.raises(ValueError):
        Settings(assessment_trusted_runtimes=[policy, policy])
    assert Settings().assessment_trusted_runtimes == []


def test_empty_runtime_migration_roundtrip(service):
    s = service("assessment")
    config = migration_config(s.app.state.settings)
    command.downgrade(config, "0008_assessment")
    assert s.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert s.client.get("/health/ready").status_code == 200
