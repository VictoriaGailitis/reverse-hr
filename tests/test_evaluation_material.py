import hashlib
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_assessment_lifecycle import setup as lifecycle_setup
from test_assessment_lifecycle import start, submit
from test_event_transport import signatures as signatures_fixture

from reverse_hr.db import Outbox
from reverse_hr.domains.assessment import ContentPackage, ContentRevision
from reverse_hr.domains.assessment_sessions import PracticalSession
from reverse_hr.domains.evaluation import (
    EvaluationIntake,
    process_deletion_request,
    process_submission,
)
from reverse_hr.evaluation_access import (
    MATERIAL_REQUEST,
    MATERIAL_RESPONSE,
    MAX_MATERIAL_BYTES,
    MaterialAccess,
    MaterialReceipt,
    MaterialRequest,
)
from reverse_hr.evaluation_material import prepare_one
from reverse_hr.events import EventEnvelope
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import canonical, sign

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures):
    lifecycle = lifecycle_setup.__wrapped__(service, token)
    start(lifecycle)
    assert submit(lifecycle).status_code == 200
    assessment = lifecycle[0][1]
    assessment.app.state.assessment_signatures = signatures["assessment"]
    with Session(assessment.app.state.engine) as session:
        event = next(
            EventEnvelope.model_validate(r.envelope)
            for r in session.scalars(select(Outbox))
            if r.envelope["event_type"] == "assessment.stage_submitted.v1"
        )
    target = service("evaluation")
    with Session(target.app.state.engine) as session, session.begin():
        process_submission(session, event, target.app.state.processing_access)
    access = MaterialAccess(target.app.state.settings)
    access._signatures = signatures["evaluation"]
    access.check_assessment = Mock()

    def send(raw, signature):
        reply = assessment.client.post(
            "/internal/v1/evaluation-material",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    access.send_material = send
    return target, assessment, event, access, lifecycle


def fetch(setup, **changes):
    _, _, event, access, _ = setup
    return access.fetch(**(event.payload | changes))


def intake(setup):
    with Session(setup[0].app.state.engine) as session:
        return session.get(EvaluationIntake, str(setup[2].aggregate_id))


def test_signed_pins_prepare_and_private_status(setup):
    target, assessment, event, access, lifecycle = setup
    material = fetch(setup)
    with Session(assessment.app.state.engine) as session:
        revision = session.get(ContentRevision, str(material.revision_id))
        assert (
            material.content_digest
            == hashlib.sha256(
                canonical(ContentPackage.model_validate(revision.content))
            ).hexdigest()
        )
        row = session.get(PracticalSession, str(event.payload["session_id"]))
        assert material.plan_version_id == UUID(row.plan_version_id)
        assert material.consent_id == UUID(row.consent_id)
    assert material.snapshot_digest == lifecycle[1]["digest"]
    assert material.snapshot_version == lifecycle[1]["version"]
    assert material.task.reference_answer and sum(c.points for c in material.task.rubric) == 100
    assert prepare_one(target.app.state.engine, access)
    assert not prepare_one(target.app.state.engine, access)
    row = intake(setup)
    assert row.status == "material_ready" and row.version == 2 and row.material_attempts == 1
    assert row.material == material.model_dump(mode="json")
    access.check_assessment.assert_called_once_with(
        event.payload["candidate_id"], material.consent_id
    )
    reply = target.client.get(
        f"/v1/evaluations/stages/{event.aggregate_id}", headers=lifecycle[0][2]
    )
    assert reply.status_code == 200 and reply.json()["score"] is None
    assert "reference_answer" not in reply.text and "rubric" not in reply.text
    with Session(target.app.state.engine) as session:
        events = list(session.scalars(select(Outbox)))
        assert len(events) == 2
        ready = next(
            r.envelope for r in events if r.envelope["event_type"] == "evaluation.material_ready.v1"
        )
        assert ready["aggregate_version"] == 2
        assert set(ready["payload"]) == set(event.payload)


@pytest.mark.parametrize(
    "key", ["candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id"]
)
def test_wrong_artifact_binding_denied(setup, key):
    with pytest.raises(HTTPException) as exc:
        fetch(setup, **{key: uuid4()})
    assert exc.value.status_code == 409


def test_retired_revision_keeps_pinned_rubric(setup):
    material = fetch(setup)
    with Session(setup[1].app.state.engine) as session, session.begin():
        revision = session.get(ContentRevision, str(material.revision_id))
        revision.status, revision.version = "retired", revision.version + 1
    assert fetch(setup) == material


def test_nonce_replay_wrong_context_and_expiry(setup):
    _, assessment, event, access, _ = setup
    body = MaterialRequest(
        **event.payload, requester="evaluation", nonce=uuid4(), issued_at=datetime.now(UTC)
    )
    headers = {
        "Content-Type": "application/json",
        "X-HR-Signature": sign(access.signatures, MATERIAL_REQUEST, body),
    }
    path = "/internal/v1/evaluation-material"
    assert assessment.client.post(path, content=canonical(body), headers=headers).status_code == 200
    assert assessment.client.post(path, content=canonical(body), headers=headers).status_code == 401
    wrong = body.model_copy(update={"nonce": uuid4()})
    headers["X-HR-Signature"] = sign(access.signatures, MATERIAL_RESPONSE, wrong)
    assert (
        assessment.client.post(path, content=canonical(wrong), headers=headers).status_code == 401
    )
    stale = body.model_copy(
        update={"nonce": uuid4(), "issued_at": datetime.now(UTC) - timedelta(minutes=1)}
    )
    headers["X-HR-Signature"] = sign(access.signatures, MATERIAL_REQUEST, stale)
    assert (
        assessment.client.post(path, content=canonical(stale), headers=headers).status_code == 401
    )
    assert assessment.client.post(path, json=body.model_dump(mode="json")).status_code == 401


@pytest.mark.parametrize("mode", ["tamper", "nonce", "oversize", "invalid_rubric"])
def test_untrusted_response_fails_closed(setup, mode):
    access = setup[3]
    original = access.send_material

    def corrupt(raw, signature):
        reply, signed = original(raw, signature)
        if mode == "oversize":
            return b"x" * (MAX_MATERIAL_BYTES + 1), signed
        if mode == "tamper":
            return reply + b" ", signed
        receipt = MaterialReceipt.model_validate_json(reply)
        if mode == "nonce":
            receipt = receipt.model_copy(update={"nonce": uuid4()})
            return canonical(receipt), sign(
                setup[1].app.state.assessment_signatures, MATERIAL_RESPONSE, receipt
            )
        data = receipt.model_dump(mode="json")
        data["material"]["task"]["rubric"][0]["points"] = 0
        import json

        return json.dumps(data).encode(), signed

    access.send_material = corrupt
    with pytest.raises(HTTPException) as exc:
        fetch(setup)
    assert exc.value.status_code == 503
    assert intake(setup).material is None


@pytest.mark.parametrize("code", [409, 503])
def test_assessment_consent_unavailable_or_revoked(setup, code):
    setup[1].app.state.processing_access.check_assessment = Mock(side_effect=HTTPException(code))
    with pytest.raises(HTTPException) as exc:
        fetch(setup)
    assert exc.value.status_code == code
    assert prepare_one(setup[0].app.state.engine, setup[3])
    row = intake(setup)
    assert row.material is None
    assert row.status == ("material_blocked" if code == 409 else "material_retry")


def test_bounded_retries_leave_no_zero_score(setup):
    target, _, _, access, _ = setup
    access.fetch = Mock(side_effect=HTTPException(503))
    now = datetime.now(UTC)
    assert prepare_one(target.app.state.engine, access, now=now, max_attempts=2, retry_seconds=5)
    assert not prepare_one(target.app.state.engine, access, now=now, max_attempts=2)
    assert prepare_one(
        target.app.state.engine, access, now=now + timedelta(seconds=6), max_attempts=2
    )
    assert intake(setup).status == "material_unavailable"
    assert intake(setup).material_attempts == 2 and intake(setup).material is None
    assert not prepare_one(target.app.state.engine, access, now=now + timedelta(hours=1))


def test_commit_failure_retry_does_not_partially_prepare(setup, monkeypatch):
    from reverse_hr import evaluation_material

    target, _, _, access, _ = setup
    original = evaluation_material.enqueue
    monkeypatch.setattr(evaluation_material, "enqueue", Mock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        prepare_one(target.app.state.engine, access)
    assert intake(setup).material is None and intake(setup).version == 1
    monkeypatch.setattr(evaluation_material, "enqueue", original)
    assert prepare_one(target.app.state.engine, access)


def deletion(event):
    request_id = uuid4()
    return EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": event.payload["candidate_id"], "request_id": request_id},
    )


def test_deletion_during_remote_fetch_cannot_restore_material(setup):
    target, _, event, access, _ = setup
    original = access.fetch

    def fetch_then_delete(**refs):
        material = original(**refs)
        with Session(target.app.state.engine) as session, session.begin():
            process_deletion_request(session, deletion(event))
        return material

    access.fetch = fetch_then_delete
    assert prepare_one(target.app.state.engine, access)
    assert intake(setup) is None
    with Session(target.app.state.engine) as session:
        assert [r.envelope["event_type"] for r in session.scalars(select(Outbox))] == [
            "evaluation.data_deleted.v1"
        ]


def test_delete_prepared_material_purges_private_rubric_and_outbox(setup):
    target, _, event, access, _ = setup
    assert prepare_one(target.app.state.engine, access)
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(event))
    assert intake(setup) is None
    with Session(target.app.state.engine) as session:
        assert [r.envelope["event_type"] for r in session.scalars(select(Outbox))] == [
            "evaluation.data_deleted.v1"
        ]


def test_permission_rechecked_after_material_response(setup):
    setup[3].check_assessment = Mock(side_effect=HTTPException(409))
    assert prepare_one(setup[0].app.state.engine, setup[3])
    assert intake(setup).status == "material_blocked" and intake(setup).material is None


def test_downgrade_protects_material_and_readiness(setup):
    assert prepare_one(setup[0].app.state.engine, setup[3])
    with pytest.raises(RuntimeError, match="populated Evaluation"):
        command.downgrade(migration_config(setup[0].app.state.settings), "0002_evaluation")
    assert setup[0].client.get("/health/ready").status_code == 200
    with pytest.raises(RuntimeError, match="populated assessment"):
        command.downgrade(migration_config(setup[1].app.state.settings), "0005_assessment")
    assert setup[1].client.get("/health/ready").status_code == 200


def test_real_consent_check_for_evaluation_and_private_status_revocation(
    setup, service, token, signatures
):
    from test_access import headers
    from test_processing_access import connect_access

    target, assessment, event, access, lifecycle = setup
    privacy = service("privacy")
    privacy.app.state.privacy_signatures = signatures["privacy"]
    auth = token(event.payload["candidate_id"])
    consent = privacy.client.post(
        "/v1/consents",
        headers=headers(auth),
        json={"purpose": "assessment", "document_version": "demo-v1"},
    )
    assert consent.status_code == 201
    consent = consent.json()
    with Session(assessment.app.state.engine) as session, session.begin():
        session.get(PracticalSession, str(event.payload["session_id"])).consent_id = consent[
            "consent_id"
        ]

    def send_permission(raw, signature):
        reply = privacy.client.post(
            "/internal/v1/assessment-permission",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    assessment.app.state.processing_access = connect_access("assessment", privacy, signatures)
    assessment.app.state.processing_access.send_assessment = send_permission
    target.app.state.processing_access = connect_access("evaluation", privacy, signatures)
    target.app.state.processing_access.send_assessment = send_permission
    access.send_assessment = send_permission
    access.check_assessment = MaterialAccess.check_assessment.__get__(access)
    assert prepare_one(target.app.state.engine, access)
    path = f"/v1/evaluations/stages/{event.aggregate_id}"
    assert target.client.get(path, headers=lifecycle[0][2]).status_code == 200
    assert (
        privacy.client.post(
            f"/v1/consents/{consent['consent_id']}/revoke",
            headers=headers(auth, "revoke", 1),
        ).status_code
        == 200
    )
    assert target.client.get(path, headers=auth).status_code == 409
    with pytest.raises(HTTPException) as exc:
        fetch(setup)
    assert exc.value.status_code == 409


def test_concurrent_preparation_cas_commits_one_material_event(setup):
    target, _, _, access, _ = setup
    original = access.fetch
    entered = False

    def overlapping(**refs):
        nonlocal entered
        material = original(**refs)
        if not entered:
            entered = True
            assert prepare_one(target.app.state.engine, access)
        return material

    access.fetch = overlapping
    assert prepare_one(target.app.state.engine, access)
    row = intake(setup)
    assert row.version == 2 and row.material_attempts == 1
    with Session(target.app.state.engine) as session:
        assert (
            sum(
                r.envelope["event_type"] == "evaluation.material_ready.v1"
                for r in session.scalars(select(Outbox))
            )
            == 1
        )


def test_non_submitted_stage_cannot_export_material(setup):
    from reverse_hr.domains.assessment_sessions import StageState

    with Session(setup[1].app.state.engine) as session, session.begin():
        session.get(StageState, str(setup[2].aggregate_id)).status = "active"
    with pytest.raises(HTTPException) as exc:
        fetch(setup)
    assert exc.value.status_code == 409


def test_assessment_tombstone_prevents_material_export(setup):
    from reverse_hr.domains.assessment_sessions import process_deletion_request as erase

    with Session(setup[1].app.state.engine) as session, session.begin():
        erase(session, deletion(setup[2]))
    with pytest.raises(HTTPException) as exc:
        fetch(setup)
    assert exc.value.status_code == 409


def test_retry_backoff_starts_after_slow_request_finishes(setup, monkeypatch):
    from reverse_hr import evaluation_material

    started = datetime.now(UTC)
    completed = started + timedelta(seconds=20)
    timeline = iter((started, completed))

    class WorkerClock:
        @classmethod
        def now(cls, timezone):
            return next(timeline)

    monkeypatch.setattr(evaluation_material, "datetime", WorkerClock)
    setup[3].fetch = Mock(side_effect=HTTPException(503))
    assert prepare_one(setup[0].app.state.engine, setup[3])
    available = intake(setup).material_available_at.replace(tzinfo=UTC)
    assert available == completed + timedelta(seconds=5)
