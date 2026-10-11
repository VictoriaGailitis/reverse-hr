"""Actual Ed25519/TestClient suite admission; no Linux execution certification."""

import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.suite_pin import SuitePin
from reverse_hr.contracts.suite_validation import build_plan
from reverse_hr.contracts.test_suites import SuiteDefinition, digest
from reverse_hr.protocols.suite_admission import (
    MAX_BYTES,
    SUITE_REQUEST,
    SUITE_RESPONSE,
    SuiteAdmissionAccess,
    SuiteAdmissionRequest,
    SuitePermit,
)
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_sessions import process_deletion_request
from reverse_hr.services.assessment.domain.assessment_tests import TestSuite as SuiteRecord
from reverse_hr.shared.signing import canonical, sign, verify
from tests.services.assessment.test_assessment_tests import create
from tests.services.assessment.test_assessment_tests import setup as content_setup
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures):
    content = content_setup.__wrapped__(service, token)
    first = create(content)
    assessment, author, reviewer, owner, revision, _ = content
    assert (
        assessment.client.post(
            f"/v1/test-suites/{first['suite_id']}/review",
            headers=headers(reviewer, "review", 1),
            json={"reason": "Synthetic independent review"},
        ).status_code
        == 200
    )
    assessment.app.state.assessment_signatures = signatures["assessment"]
    runner = service("code-runner")
    access = SuiteAdmissionAccess(runner.app.state.settings)
    access._signatures = signatures["code-runner"]
    definition = SuiteDefinition.model_validate(first["definition"])
    pin = SuitePin(
        suite_id=first["suite_id"],
        revision_id=revision,
        content_digest=first["content_digest"],
        definition_digest=first["definition_digest"],
        runtime_fingerprint="b" * 64,
    )
    plan = build_plan(definition, pin, uuid4())

    def send(raw, signature):
        reply = assessment.client.post(
            "/internal/v1/suite-validation-admission",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise ValueError(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    access.send_permit = send
    return SimpleNamespace(
        assessment=assessment,
        runner=runner,
        content=content,
        owner=owner,
        author=author,
        reviewer=reviewer,
        definition=definition,
        plan=plan,
        access=access,
        signatures=signatures,
        send=send,
    )


def request(s, **updates):
    return SuiteAdmissionRequest(
        candidate_id=s.owner,
        requester="code-runner",
        purpose="suite-validation",
        validation_id=s.plan.validation_id,
        pin=s.plan.pin,
        plan_digest=digest(s.plan),
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    ).model_copy(update=updates)


def post(s, body, signature=None):
    signature = signature or sign(s.signatures["code-runner"], SUITE_REQUEST, body)
    return s.assessment.client.post(
        "/internal/v1/suite-validation-admission",
        content=canonical(body),
        headers={"Content-Type": "application/json", "X-HR-Signature": signature},
    )


def test_signed_author_admission_and_no_private_payload(setup):
    s = setup
    assert s.access.check(s.owner, s.plan) is None
    body = request(s)
    reply = post(s, body)
    assert reply.status_code == 200 and reply.json()["allowed"] is True
    receipt = SuitePermit.model_validate_json(reply.content)
    verify(
        s.signatures["assessment"],
        "assessment",
        reply.headers["X-HR-Signature"],
        SUITE_RESPONSE,
        receipt,
    )
    assert len(reply.content) < MAX_BYTES
    assert set(reply.json()) == set(body.model_dump()) | {"allowed"}
    assert "expected_stdout" not in reply.text and "main.py" not in reply.text
    assert post(s, body).status_code == 401
    assert s.access.check(s.owner, s.plan) is None


@pytest.mark.parametrize(
    "field",
    [
        "candidate_id",
        "validation_id",
        "plan_digest",
        "suite_id",
        "revision_id",
        "definition_digest",
        "content_digest",
    ],
)
def test_foreign_bindings_receive_signed_denial(setup, field):
    s = setup
    body = request(s)
    if field in {"candidate_id", "validation_id", "plan_digest"}:
        body = body.model_copy(update={field: "f" * 64 if field == "plan_digest" else uuid4()})
    else:
        body = body.model_copy(
            update={
                "pin": body.pin.model_copy(
                    update={field: uuid4() if field.endswith("_id") else "f" * 64}
                )
            }
        )
    reply = post(s, body)
    assert reply.status_code == 200 and reply.json()["allowed"] is False


@pytest.mark.parametrize("retired", ["draft", "suite", "content", "owner", "privacy"])
def test_current_status_and_processing_close_admission(setup, retired):
    s = setup
    if retired == "draft":
        with Session(s.assessment.app.state.engine) as session, session.begin():
            session.get(SuiteRecord, str(s.plan.pin.suite_id)).status = "draft"
    elif retired in {"suite", "content"}:
        path = (
            f"/v1/test-suites/{s.plan.pin.suite_id}/retire"
            if retired == "suite"
            else f"/v1/content-versions/{s.plan.pin.revision_id}/retire"
        )
        assert (
            s.assessment.client.post(
                path,
                headers=headers(s.reviewer, "withdraw", 2),
                json={"reason": "Withdraw synthetic item"},
            ).status_code
            == 200
        )
    elif retired == "privacy":
        s.assessment.app.state.processing_access.check = Mock(side_effect=HTTPException(409))
    else:
        request_id = uuid4()
        event = EventEnvelope(
            producer="privacy",
            event_type="privacy.deletion_requested.v1",
            correlation_id=uuid4(),
            aggregate_id=request_id,
            aggregate_version=1,
            payload={"candidate_id": s.owner, "request_id": request_id},
        )
        with Session(s.assessment.app.state.engine) as session, session.begin():
            process_deletion_request(session, event)
    with pytest.raises(HTTPException) as exc:
        s.access.check(s.owner, s.plan)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("bad", ["signature", "producer", "context", "expired", "future", "naive"])
def test_request_authentication_and_freshness(setup, bad):
    s = setup
    body = request(s)
    signature = None
    if bad == "signature":
        signature = "invalid"
    elif bad == "producer":
        signature = sign(s.signatures["evaluation"], SUITE_REQUEST, body)
    elif bad == "context":
        signature = sign(s.signatures["code-runner"], SUITE_RESPONSE, body)
    else:
        issued = datetime.now(UTC) + timedelta(minutes=5 if bad == "future" else -5)
        if bad == "naive":
            issued = datetime.now()
        body = body.model_copy(update={"issued_at": issued})
    assert post(s, body, signature).status_code == 401


@pytest.mark.parametrize(
    "bad",
    [
        "nonce",
        "owner",
        "plan",
        "runtime",
        "validation",
        "allowed",
        "context",
        "signature",
        "stale",
        "canonical",
        "oversize",
    ],
)
def test_client_rejects_unbound_or_invalid_receipt(setup, bad):
    s = setup

    def altered(raw, signature):
        data, _ = s.send(raw, signature)
        receipt = SuitePermit.model_validate_json(data)
        if bad == "nonce":
            receipt.nonce = uuid4()
        elif bad == "owner":
            receipt.candidate_id = uuid4()
        elif bad == "plan":
            receipt.plan_digest = "f" * 64
        elif bad == "validation":
            receipt.validation_id = uuid4()
        elif bad == "runtime":
            receipt.pin.runtime_fingerprint = "f" * 64
        elif bad == "stale":
            receipt.issued_at -= timedelta(minutes=5)
        result = canonical(receipt)
        if bad == "allowed":
            result = result.replace(b'"allowed":true', b'"allowed":1')
        elif bad == "canonical":
            result = json.dumps(receipt.model_dump(mode="json")).encode()
        elif bad == "oversize":
            result += b" " * MAX_BYTES
        signed = sign(
            s.signatures["assessment"],
            SUITE_REQUEST if bad == "context" else SUITE_RESPONSE,
            receipt,
        )
        return result, "invalid" if bad == "signature" else signed

    s.access.send_permit = altered
    with pytest.raises(HTTPException) as exc:
        s.access.check(s.owner, s.plan)
    assert exc.value.status_code == 503


def test_unavailable_processing_rolls_back_nonce_and_corruption_is_technical(setup):
    s = setup
    body = request(s)
    s.assessment.app.state.processing_access.check = Mock(side_effect=HTTPException(503))
    assert post(s, body).status_code == 503
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(MaterialNonce, str(body.nonce)) is None
    s.assessment.app.state.processing_access.check = Mock(return_value=None)
    assert post(s, body).json()["allowed"] is True
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(SuiteRecord, str(s.plan.pin.suite_id))
        changed = dict(row.definition)
        changed["comparison_policy"] = "invalid"
        row.definition = changed
    assert post(s, request(s)).status_code == 503


def test_changed_complete_plan_is_denied_even_with_valid_suite_pins(setup):
    s = setup
    changed = s.plan.model_copy(deep=True)
    changed.inputs[0].manifest.files[0].content = "altered source"
    changed.inputs[0].manifest_digest = digest(changed.inputs[0].manifest)
    with pytest.raises(HTTPException) as exc:
        s.access.check(s.owner, changed)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("retire", [False, True])
def test_actual_signed_admission_gates_durable_validation_scope(
    setup, tmp_path, monkeypatch, retire
):
    import reverse_hr.services.code_runner.validation_lifecycle as lifecycle
    from reverse_hr.platform.settings import Settings
    from reverse_hr.services.code_runner.sandbox import NsjailExecutor

    s = setup
    scratch, groups = tmp_path / "scratch", tmp_path / "groups"
    scratch.mkdir(mode=0o700)
    groups.mkdir()
    node = uuid4()
    executor = NsjailExecutor(
        Settings(
            service_name="code-runner",
            runner_node_id=node,
            runner_scratch=str(scratch),
            runner_cgroup_parent=str(groups),
        )
    )
    monkeypatch.setattr(executor, "validate", lambda: None)
    monkeypatch.setattr(lifecycle, "require_execution_ready", lambda *_: None)
    monkeypatch.setattr(lifecycle, "fingerprint", lambda *_: s.plan.pin.runtime_fingerprint)
    engine, processing = s.runner.app.state.engine, s.runner.app.state.processing_access
    lifecycle.register(engine, s.owner, processing, s.definition, s.plan)
    attempt_id = lifecycle.reserve(
        engine, s.owner, s.plan.validation_id, processing, node, executor
    )
    scope = lifecycle.validation_scope(engine, processing, s.access, node, attempt_id, executor)
    if retire:
        assert (
            s.assessment.client.post(
                f"/v1/test-suites/{s.plan.pin.suite_id}/retire",
                headers=headers(s.reviewer, "retire", 2),
                json={"reason": "Synthetic withdrawal"},
            ).status_code
            == 200
        )
        with pytest.raises(HTTPException) as exc, scope:
            pytest.fail("Retired suite admitted")
        assert exc.value.status_code == 409
    else:
        with scope as item:
            assert item == s.plan.inputs[0]
    with Session(engine) as session:
        assert session.get(lifecycle.ValidationAttempt, str(attempt_id)).state == (
            "reserved" if retire else "active"
        )
    assert lifecycle.recover_one(engine, node, executor)


@pytest.mark.parametrize(
    "field,value",
    [("purpose", "candidate-grading"), ("requester", "evaluation"), ("allowed", True)],
)
def test_endpoint_rejects_wrong_purpose_requester_or_client_grant(setup, field, value):
    s = setup
    body = request(s)
    data = body.model_dump(mode="json") | {field: value}
    reply = s.assessment.client.post(
        "/internal/v1/suite-validation-admission",
        json=data,
        headers={"X-HR-Signature": sign(s.signatures["code-runner"], SUITE_REQUEST, body)},
    )
    assert reply.status_code == 422


def test_missing_signature_or_signing_failure_never_consumes_nonce(setup, monkeypatch):
    import reverse_hr.services.assessment.domain.assessment_suite_admission as domain

    s = setup
    body = request(s)
    assert (
        s.assessment.client.post(
            "/internal/v1/suite-validation-admission", json=body.model_dump(mode="json")
        ).status_code
        == 401
    )
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(MaterialNonce, str(body.nonce)) is None
    monkeypatch.setattr(domain, "sign", Mock(side_effect=RuntimeError("Synthetic signing failure")))
    assert post(s, body).status_code == 503
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(MaterialNonce, str(body.nonce)) is None
