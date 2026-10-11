"""Actual nested signatures/intake; upstream executor/probe remain synthetic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.suite_verdict import VERDICT_CONTEXT
from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.verdict_delivery import (
    INTAKE_REQUEST,
    INTAKE_RESPONSE,
    VerdictDelivery,
    VerdictDeliveryAccess,
    VerdictReceipt,
)
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_sessions import process_deletion_request
from reverse_hr.services.assessment.domain.assessment_verdicts import ValidationIntake
from reverse_hr.shared.db import Outbox
from reverse_hr.shared.signing import canonical, sign
from tests.services.code_runner.test_code_runner import deletion
from tests.services.code_runner.test_validation_verdict import finish
from tests.services.code_runner.test_validation_verdict import setup as verdict_setup
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch):
    s = verdict_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    s.proof, s.proof_signature = finish(s)
    access = VerdictDeliveryAccess(s.runner.app.state.settings)
    access._signatures = signatures["code-runner"]

    def send(raw, signature):
        response = s.assessment.client.post(
            "/internal/v1/suite-validation-verdict",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise ValueError(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    s.delivery, s.send = access, send
    access.send_verdict = send
    return s


def body(s, proof=None, proof_signature=None):
    return VerdictDelivery(
        candidate_id=(proof or s.proof).owner_id,
        requester="code-runner",
        purpose="suite-verdict-intake",
        proof=proof or s.proof,
        proof_signature=proof_signature or s.proof_signature,
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )


def post(s, request, signature=None):
    return s.assessment.client.post(
        "/internal/v1/suite-validation-verdict",
        content=canonical(request),
        headers={
            "Content-Type": "application/json",
            "X-HR-Signature": signature
            or sign(s.signatures["code-runner"], INTAKE_REQUEST, request),
        },
    )


def rows(s, model):
    with Session(s.assessment.app.state.engine) as session:
        return session.scalars(select(model)).all()


def test_signed_intake_natural_replay_and_private_history_without_scoring(setup):
    s = setup
    receipt = s.delivery.deliver(s.proof, s.proof_signature)
    assert receipt.allowed and receipt.verdict == "accepted"
    assert not receipt.runtime_validated and not receipt.scoring_enabled
    assert s.delivery.deliver(s.proof, s.proof_signature).allowed
    assert len(rows(s, ValidationIntake)) == 1
    events = [
        row.envelope
        for row in rows(s, Outbox)
        if "validation_verdict_received" in row.envelope["event_type"]
    ]
    assert len(events) == 1 and set(events[0]["payload"]) == {
        "candidate_id",
        "suite_id",
        "validation_id",
    }
    path = f"/v1/test-suites/{s.proof.pin.suite_id}/validations/{s.proof.validation_id}"
    response = s.assessment.client.get(path, headers=s.reviewer)
    assert response.status_code == 200 and response.json()["signature_verified"]
    assert not response.json()["runtime_validated"] and not response.json()["scoring_enabled"]
    suite = s.assessment.client.get(
        f"/v1/test-suites/{s.proof.pin.suite_id}", headers=s.reviewer
    ).json()
    assert (
        suite["version"] == 2 and suite["status"] == "reviewed" and not suite["runtime_validated"]
    )
    request = body(s)
    assert post(s, request).status_code == 200
    assert post(s, request).status_code == 401


@pytest.mark.parametrize("bad", ["structure", "signature", "owner"])
def test_history_rejects_corrupt_record(setup, bad):
    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(ValidationIntake, str(s.proof.validation_id))
        if bad == "structure":
            row.proof = {"verdict": "accepted"}
        elif bad == "signature":
            row.proof_signature = "invalid"
        else:
            row.owner_id = str(uuid4())
    path = f"/v1/test-suites/{s.proof.pin.suite_id}/validations/{s.proof.validation_id}"
    assert s.assessment.client.get(path, headers=s.reviewer).status_code == 409


@pytest.mark.parametrize(
    "roles,mfa",
    [
        (("candidate",), True),
        (("employer",), True),
        (("assessment_reviewer",), True),
        (("content_admin",), False),
    ],
)
def test_history_is_mfa_content_admin_only(setup, token, roles, mfa):
    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    path = f"/v1/test-suites/{s.proof.pin.suite_id}/validations/{s.proof.validation_id}"
    assert (
        s.assessment.client.get(
            path, headers=token(roles=roles, amr=["mfa"] if mfa else [])
        ).status_code
        == 403
    )
    assert s.assessment.client.get(path).status_code == 401
    assert (
        s.assessment.client.get(
            path.replace(str(s.proof.pin.suite_id), str(uuid4())), headers=s.reviewer
        ).status_code
        == 404
    )


@pytest.mark.parametrize(
    "bad",
    [
        "transport_key",
        "transport_context",
        "proof_key",
        "proof_context",
        "proof_data",
        "stale_request",
        "future_proof",
        "naive_proof",
    ],
)
def test_both_signatures_and_times_are_required(setup, bad):
    s = setup
    proof, proof_signature = s.proof, s.proof_signature
    signature = None
    if bad == "proof_key":
        proof_signature = sign(s.signatures["evaluation"], VERDICT_CONTEXT, proof)
    elif bad == "proof_context":
        proof_signature = sign(s.signatures["code-runner"], INTAKE_REQUEST, proof)
    elif bad in {"proof_data", "future_proof", "naive_proof"}:
        proof = proof.model_copy(
            update={"captures_digest": "f" * 64}
            if bad == "proof_data"
            else {
                "completed_at": datetime.now(UTC) + timedelta(hours=1)
                if bad == "future_proof"
                else datetime.now()
            }
        )
        if bad != "proof_data":
            proof_signature = sign(s.signatures["code-runner"], VERDICT_CONTEXT, proof)
    request = body(s, proof, proof_signature)
    if bad == "transport_key":
        signature = sign(s.signatures["evaluation"], INTAKE_REQUEST, request)
    elif bad == "transport_context":
        signature = sign(s.signatures["code-runner"], INTAKE_RESPONSE, request)
    elif bad == "stale_request":
        request.issued_at -= timedelta(minutes=5)
    assert post(s, request, signature).status_code == 401
    assert not rows(s, ValidationIntake)


@pytest.mark.parametrize(
    "field", ["owner", "revision", "definition", "plan", "count", "predates_suite"]
)
def test_validly_signed_foreign_claims_are_denied(setup, field):
    s = setup
    proof = s.proof.model_copy(deep=True)
    if field == "owner":
        proof.owner_id = uuid4()
    elif field == "revision":
        proof.pin.revision_id = uuid4()
    elif field == "definition":
        proof.pin.definition_digest = "f" * 64
    elif field == "plan":
        proof.plan_digest = "f" * 64
    elif field == "count":
        proof.captures_count += 1
    else:
        proof.completed_at -= timedelta(days=1)
    response = post(s, body(s, proof, sign(s.signatures["code-runner"], VERDICT_CONTEXT, proof)))
    assert response.status_code == 200 and response.json()["allowed"] is False
    assert not rows(s, ValidationIntake)


@pytest.mark.parametrize("retire", ["suite", "content", "processing"])
def test_replay_checks_current_admission(setup, retire):
    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    if retire == "processing":
        s.assessment.app.state.processing_access.check = Mock(side_effect=HTTPException(409))
    else:
        path = (
            f"/v1/test-suites/{s.proof.pin.suite_id}/retire"
            if retire == "suite"
            else f"/v1/content-versions/{s.proof.pin.revision_id}/retire"
        )
        assert (
            s.assessment.client.post(
                path, headers=headers(s.reviewer, "withdraw", 2), json={"reason": "Withdrawal"}
            ).status_code
            == 200
        )
    with pytest.raises(HTTPException) as exc:
        s.delivery.deliver(s.proof, s.proof_signature)
    assert exc.value.status_code == 409


def test_conflicting_same_batch_cannot_replace_history(setup):
    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    changed = s.proof.model_copy(update={"verdict": "rejected"})
    assert (
        post(
            s, body(s, changed, sign(s.signatures["code-runner"], VERDICT_CONTEXT, changed))
        ).status_code
        == 409
    )
    assert rows(s, ValidationIntake)[0].proof["verdict"] == "accepted"


@pytest.mark.parametrize("failure", ["processing", "outbox", "signing"])
def test_failed_intake_rolls_back_nonce_record_and_outbox(setup, monkeypatch, failure):
    import reverse_hr.services.assessment.domain.assessment_verdicts as domain

    s = setup
    request = body(s)
    if failure == "processing":
        s.assessment.app.state.processing_access.check = Mock(side_effect=HTTPException(503))
    else:
        monkeypatch.setattr(
            domain,
            "enqueue" if failure == "outbox" else "sign",
            Mock(side_effect=HTTPException(503)),
        )
    assert post(s, request).status_code == 503
    assert not rows(s, ValidationIntake)
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(MaterialNonce, str(request.nonce)) is None


@pytest.mark.parametrize(
    "change",
    ["nonce", "owner", "batch", "digest", "context", "signature", "stale", "oversize", "grading"],
)
def test_client_rejects_unbound_receipt(setup, change):
    s = setup

    def altered(raw, signature):
        data, _ = s.send(raw, signature)
        receipt = VerdictReceipt.model_validate_json(data)
        if change == "nonce":
            receipt.nonce = uuid4()
        elif change == "owner":
            receipt.candidate_id = uuid4()
        elif change == "batch":
            receipt.validation_id = uuid4()
        elif change == "digest":
            receipt.proof_digest = "f" * 64
        elif change == "stale":
            receipt.issued_at -= timedelta(minutes=5)
        elif change == "grading":
            receipt.scoring_enabled = True
        data = canonical(receipt) + (b" " * 4096 if change == "oversize" else b"")
        signed = sign(
            s.signatures["assessment"],
            INTAKE_REQUEST if change == "context" else INTAKE_RESPONSE,
            receipt,
        )
        return data, "invalid" if change == "signature" else signed

    s.delivery.send_verdict = altered
    with pytest.raises(HTTPException) as exc:
        s.delivery.deliver(s.proof, s.proof_signature)
    assert exc.value.status_code == 503


def test_delete_purges_intake_and_blocks_late_delivery(setup):
    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    with Session(s.assessment.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.owner))
    assert not rows(s, ValidationIntake)
    assert not [
        row
        for row in rows(s, Outbox)
        if "validation_verdict_received" in row.envelope["event_type"]
    ]
    with pytest.raises(HTTPException) as exc:
        s.delivery.deliver(s.proof, s.proof_signature)
    assert exc.value.status_code == 409


def test_populated_and_empty_migration_guards(setup):
    s = setup
    s.delivery.deliver(s.proof, s.proof_signature)
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.assessment.app.state.settings), "0007_assessment")
    assert s.assessment.client.get("/health/ready").status_code == 200


def test_empty_migration_roundtrip(service):
    target = service("assessment")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0007_assessment")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200
