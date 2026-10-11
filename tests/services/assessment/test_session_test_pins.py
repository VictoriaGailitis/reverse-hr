"""Actual signed suite/material RPC; upstream runtime and snapshot receipt are synthetic."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.session_test_pins import PlanPins, SessionPins, stored_pins
from reverse_hr.contracts.test_suites import digest
from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.evaluation_access import MaterialAccess
from reverse_hr.protocols.snapshot_access import SnapshotReceipt
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PlanVersion,
    PracticalSession,
    process_deletion_request,
)
from reverse_hr.shared.db import Outbox
from tests.services.code_runner.test_code_runner import deletion
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture
from tests.shared.test_runtime_trust import setup as trust_setup

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch):
    s = trust_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    s.delivery.deliver(
        s.proof, s.proof_signature, attestation=s.report, attestation_signature=s.report_signature
    )
    s.assessment.app.state.settings.assessment_trusted_runtimes = [s.policy]
    s.selection = dict(
        revision_id=str(s.proof.pin.revision_id),
        task_key="sample",
        suite_id=str(s.proof.pin.suite_id),
        validation_id=str(s.proof.validation_id),
    )
    s.body = dict(
        name="Pinned synthetic plan",
        revision_ids=[s.selection["revision_id"]],
        reason="Synthetic policy approval",
        test_suite_selections=[s.selection],
    )
    reply = publish(s)
    assert reply.status_code == 201, reply.text
    s.version = reply.json()
    s.candidate = uuid4()
    s.auth = token(s.candidate)
    s.session_body = dict(
        plan_version_id=s.version["plan_version_id"], assessment_consent_id=str(uuid4())
    )
    return s


def publish(s, body=None, key="plan"):
    return s.assessment.client.post(
        "/v1/assessment-plans", json=body or s.body, headers=headers(s.reviewer, key)
    )


def create(s, key="session"):
    return s.assessment.client.post(
        "/v1/assessment-sessions", json=s.session_body, headers=headers(s.auth, key)
    )


def submitted(s):
    reply = create(s)
    assert reply.status_code == 201
    data = reply.json()
    s.session_id, s.stage_id = UUID(data["session_id"]), UUID(data["stages"][0]["stage_id"])
    path = f"/v1/assessment-sessions/{s.session_id}"
    assert (
        s.assessment.client.post(path + "/start", headers=headers(s.auth, "start", 1)).status_code
        == 200
    )
    assert (
        s.assessment.client.post(
            path + f"/stages/{s.stage_id}/start", headers=headers(s.auth, "stage", 2)
        ).status_code
        == 200
    )
    s.workspace_id, s.snapshot_id = uuid4(), uuid4()
    # Only the snapshot receipt is a double; downstream material transport uses real Ed25519.
    s.assessment.app.state.snapshot_access.fetch = Mock(
        return_value=SnapshotReceipt(
            candidate_id=s.candidate,
            requester="assessment",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
            session_id=s.session_id,
            stage_id=s.stage_id,
            workspace_id=s.workspace_id,
            snapshot_id=s.snapshot_id,
            allowed=True,
            format="code",
            snapshot_version=1,
            digest="c" * 64,
        )
    )
    assert (
        s.assessment.client.post(
            path + f"/stages/{s.stage_id}/submit",
            headers=headers(s.auth, "submit", 3),
            json=dict(workspace_id=str(s.workspace_id), snapshot_id=str(s.snapshot_id)),
        ).status_code
        == 200
    )
    s.material = MaterialAccess(
        s.runner.app.state.settings.model_copy(update={"service_name": "evaluation"})
    )
    s.material._signatures = s.signatures["evaluation"]

    def send(raw, signature):
        response = s.assessment.client.post(
            "/internal/v1/evaluation-material",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise ValueError(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    s.material.send_material = send


def fetch(s):
    return s.material.fetch(s.candidate, s.session_id, s.stage_id, s.workspace_id, s.snapshot_id)


def test_plan_session_copy_and_no_private_pins_in_candidate_response(setup):
    s = setup
    result = create(s)
    assert result.status_code == 201
    assert not any(
        key in result.text
        for key in (
            "test_pins",
            "expected_stdout",
            "runtime_fingerprint",
            "validation_id",
            "policy_id",
        )
    )
    with Session(s.assessment.app.state.engine) as session:
        plan = session.get(PlanVersion, s.version["plan_version_id"])
        row = session.get(PracticalSession, result.json()["session_id"])
        source = stored_pins(plan)[0]
        target = stored_pins(row, for_session=True)[0]
        assert target.pin == source.pin and target.validation_id == source.validation_id
        assert target.verdict_digest == digest(s.proof) and target.attestation_digest == digest(
            s.report
        )
        assert target.stage_id == UUID(result.json()["stages"][0]["stage_id"])
        assert plan.test_pins_digest == digest(PlanPins(pins=[source]))
        assert row.test_pins_digest == digest(SessionPins(pins=[target]))
    assert create(s).json() == result.json()


@pytest.mark.parametrize("state", ["missing", "expired", "future", "changed_id"])
def test_new_session_and_plan_replay_require_current_exact_policy(setup, state):
    s = setup
    policy = s.policy.model_copy(deep=True)
    if state == "missing":
        entries = []
    else:
        if state == "expired":
            policy.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        elif state == "future":
            policy.approved_at = datetime.now(UTC) + timedelta(hours=1)
        else:
            policy.policy_id = uuid4()
        entries = [policy]
    s.assessment.app.state.settings.assessment_trusted_runtimes = entries
    assert create(s).status_code == 409
    assert publish(s).status_code == 409
    assert s.assessment.client.get("/v1/assessment-plans", headers=s.auth).json() == []
    with Session(s.assessment.app.state.engine) as session:
        assert not session.scalars(select(PracticalSession)).all()


@pytest.mark.parametrize("bad", ["duplicate", "revision", "task", "suite", "validation"])
def test_selection_must_cover_exact_stage_and_verdict(setup, bad):
    s = setup
    choice = dict(s.selection)
    if bad == "revision":
        choice["revision_id"] = str(uuid4())
    elif bad == "task":
        choice["task_key"] = "foreign"
    elif bad == "suite":
        choice["suite_id"] = str(uuid4())
    elif bad == "validation":
        choice["validation_id"] = str(uuid4())
    body = s.body | {"test_suite_selections": [choice, choice] if bad == "duplicate" else [choice]}
    assert publish(s, body, "bad").status_code in {409, 422}
    with Session(s.assessment.app.state.engine) as session:
        assert len(session.scalars(select(PlanVersion)).all()) == 1


@pytest.mark.parametrize("bad", ["clear", "structure", "digest", "stage"])
def test_corrupted_plan_cannot_create_session(setup, bad):
    s = setup
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(PlanVersion, s.version["plan_version_id"])
        if bad == "clear":
            row.test_pins = []
        elif bad == "structure":
            row.test_pins = [{"position": 0}]
        elif bad == "digest":
            row.test_pins_digest = "f" * 64
        else:
            row.stages = [row.stages[0] | {"instruction": "tampered"}]
    assert create(s).status_code == 409


def test_signed_evaluation_material_carries_only_frozen_binding(setup):
    s = setup
    submitted(s)
    material = fetch(s)
    assert material.test_suite.stage_id == s.stage_id
    assert material.test_suite.validation_id == s.proof.validation_id
    assert (
        material.test_suite.pin == s.proof.pin
        and material.test_suite.policy_id == s.policy.policy_id
    )
    assert (
        "cases" not in material.test_suite.model_dump()
        and "definition" not in material.test_suite.model_dump()
    )
    assert material.demo
    s.assessment.app.state.settings.assessment_trusted_runtimes = []
    assert fetch(s) == material  # historical export does not grant new runtime execution
    assert (
        s.assessment.client.post(
            f"/v1/test-suites/{s.proof.pin.suite_id}/retire",
            headers=headers(s.reviewer, "retire", 2),
            json={"reason": "withdrawn"},
        ).status_code
        == 200
    )
    assert fetch(s) == material
    assert create(s, "new-after-retire").status_code == 409


def test_corrupted_session_and_deleted_suite_owner_close_material(setup):
    s = setup
    submitted(s)
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(PracticalSession, str(s.session_id))
        original = row.test_pins
        row.test_pins = []
    with pytest.raises(HTTPException):
        fetch(s)
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(PracticalSession, str(s.session_id))
        row.test_pins = original
        process_deletion_request(session, deletion(s.owner))
    with pytest.raises(HTTPException):
        fetch(s)
    assert create(s, "after-delete").status_code == 409


def test_changed_catalogue_digest_cannot_rebind_historical_material(setup):
    from reverse_hr.contracts.test_suites import SuiteDefinition
    from reverse_hr.services.assessment.domain.assessment_tests import TestSuite as SuiteRecord

    s = setup
    submitted(s)
    fetch(s)
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(SuiteRecord, str(s.proof.pin.suite_id))
        definition = SuiteDefinition.model_validate(row.definition)
        definition.cases[0].expected_stdout = "changed\n"
        row.definition = definition.model_dump(mode="json")
        row.definition_digest = digest(definition)
    with pytest.raises(HTTPException):
        fetch(s)


def test_candidate_deletion_purges_session_pins(setup):
    s = setup
    response = create(s)
    assert response.status_code == 201
    with Session(s.assessment.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate))
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(PracticalSession, response.json()["session_id"]) is None
        assert session.get(PlanVersion, s.version["plan_version_id"]) is not None
        assert not [
            e
            for e in session.scalars(select(Outbox))
            if e.envelope["event_type"] == "assessment.session_created.v1"
        ]


def test_owner_processing_unavailable_rolls_back_new_admission(setup):
    s = setup
    s.assessment.app.state.processing_access.check = Mock(side_effect=HTTPException(503))
    assert create(s).status_code == 503
    assert publish(s, key="unavailable").status_code == 503


@pytest.mark.parametrize("field", ["revision", "task", "content", "stage"])
def test_signed_foreign_suite_binding_rejected_by_material_client(setup, field):
    from reverse_hr.protocols.evaluation_access import MATERIAL_RESPONSE, MaterialReceipt
    from reverse_hr.shared.signing import canonical, sign

    s = setup
    submitted(s)
    original = s.material.send_material

    def altered(raw, signature):
        data, _ = original(raw, signature)
        receipt = MaterialReceipt.model_validate_json(data)
        pin = receipt.material.test_suite
        if field == "revision":
            pin.revision_id = uuid4()
        elif field == "task":
            pin.task_key = "foreign"
        elif field == "content":
            pin.pin.content_digest = "f" * 64
        else:
            pin.stage_id = uuid4()
        return canonical(receipt), sign(s.signatures["assessment"], MATERIAL_RESPONSE, receipt)

    s.material.send_material = altered
    with pytest.raises(HTTPException) as exc:
        fetch(s)
    assert exc.value.status_code == 503


def test_protected_pin_migration(setup):
    s = setup
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.assessment.app.state.settings), "0009_assessment")
    assert s.assessment.client.get("/health/ready").status_code == 200


def test_empty_pin_migration_roundtrip(service):
    empty = service("assessment")
    config = migration_config(empty.app.state.settings)
    command.downgrade(config, "0009_assessment")
    assert empty.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert empty.client.get("/health/ready").status_code == 200


def test_rotating_session_preserves_signed_hidden_suite_pins(setup, token):
    from tests.services.assessment.test_assessment_selection import policy

    s = setup
    second = publish(s, key="rotation-alternative")
    assert second.status_code == 201
    key, _ = policy(s.assessment, token, [s.version, second.json()])
    body = dict(selection_policy_id=key, assessment_consent_id=str(uuid4()))
    result = s.assessment.client.post(
        "/v1/assessment-selected-sessions", headers=headers(s.auth, "rotate"), json=body
    )
    assert result.status_code == 201, result.text
    assert "cases" not in result.text and "reference_answer" not in result.text
    with Session(s.assessment.app.state.engine) as session:
        row = session.get(PracticalSession, result.json()["session_id"])
        original = session.get(PlanVersion, row.plan_version_id)
        pins = stored_pins(row, for_session=True)
        assert len(pins) == 1
        assert pins[0].pin == stored_pins(original)[0].pin
        assert str(pins[0].stage_id) == result.json()["stages"][0]["stage_id"]
        assert row.selection_policy_id == key
