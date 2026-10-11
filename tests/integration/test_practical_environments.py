"""Signed active-stage admission, real persisted bytes and board submission fences."""

import base64
import hashlib
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.practical_receipts import PracticalReceiptAccess
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.protocols.recording_access import RecordingAccess
from reverse_hr.protocols.snapshot_access import SNAPSHOT_REQUEST, SnapshotRequest
from reverse_hr.protocols.stage_access import StageAccess
from reverse_hr.services.assessment.domain.assessment_sessions import StageState
from reverse_hr.services.media.domain.media import Recording, RecordingChunk
from reverse_hr.services.privacy.domain.privacy import ConsentRecord
from reverse_hr.services.whiteboard.domain.whiteboard import Board, BoardOperation, BoardSnapshot
from reverse_hr.shared.db import IdempotencyRecord, Outbox
from reverse_hr.shared.signing import canonical, sign
from tests.services.assessment.test_assessment_sessions import make_session, plan
from tests.services.assessment.test_company_tasks import package
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture


@pytest.fixture(params=[("media", "voice"), ("media", "vcv"), ("whiteboard", "whiteboard")])
def environment(request, service, token, signatures):
    name, format = request.param
    s = SimpleNamespace(name=name, format=format, signatures=signatures, subject=uuid4())
    s.assessment, s.privacy, s.env = service("assessment"), service("privacy"), service(name)
    s.auth = token(s.subject)
    s.assessment.app.state.assessment_signatures = signatures["assessment"]
    s.env.app.state.practical_signatures = signatures[name]
    s.privacy.app.state.privacy_signatures = signatures["privacy"]

    def sender(target):
        def send(endpoint, raw, signature, **kwargs):
            response = target.client.post(
                "/internal/v1/" + endpoint,
                content=raw,
                headers={"Content-Type": "application/json", "X-HR-Signature": signature},
            )
            if response.status_code != 200:
                raise ValueError(response.status_code)
            return response.content, response.headers["X-HR-Signature"]

        return send

    for target, owner in [(s.assessment, "assessment"), (s.env, name)]:
        access = ProcessingAccess(target.app.state.settings)
        access._signatures, access._send = signatures[owner], sender(s.privacy)
        target.app.state.processing_access = access
    s.stage_access = StageAccess(s.env.app.state.settings)
    s.stage_access._signatures, s.stage_access._send = signatures[name], sender(s.assessment)
    s.env.app.state.stage_access = s.stage_access
    if name == "media":
        # These API/RPC tests use synthetic container bytes. Full decode has separate real fixtures.
        from reverse_hr.services.media.media_validation import MediaValidation

        s.env.app.state.media_validator = SimpleNamespace(
            validate=lambda *_: MediaValidation(
                validator="test-only",
                duration_ms=5000,
                audio_codec="opus",
                sample_rate=48000,
                channels=1,
            )
        )
        access = RecordingAccess(s.env.app.state.settings)
        access._signatures, access._send = signatures[name], sender(s.privacy)
        s.env.app.state.recording_access = access
    receipt = PracticalReceiptAccess(s.assessment.app.state.settings)
    receipt._signatures, receipt._send = signatures["assessment"], sender(s.env)
    s.assessment.app.state.practical_receipt_access = receipt
    s.receipt = receipt
    consents = []
    for purpose in ["assessment", "recording"]:
        reply = s.privacy.client.post(
            "/v1/consents",
            headers=headers(s.auth, purpose),
            json={"purpose": purpose, "document_version": "demo-v1"},
        )
        assert reply.status_code == 201, reply.text
        consents.append(reply.json()["consent_id"])
    s.recording_consent = consents[1]
    version, _, _ = plan(s.assessment, token, package(format))
    reply, _, _ = make_session(s.assessment, token, version, s.subject, consent=UUID(consents[0]))
    assert reply.status_code == 201, reply.text
    s.session_id, s.stage_id = reply.json()["session_id"], reply.json()["stages"][0]["stage_id"]
    s.path = f"/v1/assessment-sessions/{s.session_id}"
    assert (
        s.assessment.client.post(s.path + "/start", headers=headers(s.auth, "start", 1)).status_code
        == 200
    )
    assert (
        s.assessment.client.post(
            s.path + f"/stages/{s.stage_id}/start", headers=headers(s.auth, "stage", 2)
        ).status_code
        == 200
    )
    s.raw = b"\x1aE\xdf\xa3" + b"synthetic" * 33000
    return s


def create(s, key="create", **changes):
    body = {"session_id": s.session_id, "stage_id": s.stage_id}
    if s.name == "media":
        body |= {
            "recording_consent_id": s.recording_consent,
            "mime": "audio/webm" if s.format == "voice" else "video/webm",
            "size": len(s.raw),
            "digest": hashlib.sha256(s.raw).hexdigest(),
            "client_duration_ms": 1000,
        }
    body |= changes
    reply = s.env.client.post(
        "/v1/recordings" if s.name == "media" else "/v1/boards",
        headers=headers(s.auth, key),
        json=body,
    )
    return reply


def prepared(s):
    response = create(s)
    assert response.status_code == 201, response.text
    row = response.json()
    if s.name == "media":
        ref = row["recording_id"]
        s.env_path = f"/v1/recordings/{ref}"
        for number, start in enumerate(range(0, len(s.raw), 262144)):
            data = s.raw[start : start + 262144]
            body = {
                "data_base64": base64.b64encode(data).decode(),
                "digest": hashlib.sha256(data).hexdigest(),
            }
            response = s.env.client.put(
                s.env_path + f"/chunks/{number}",
                headers=headers(s.auth, f"part-{number}", row["version"]),
                json=body,
            )
            assert response.status_code == 200, response.text
            row = response.json()
        response = s.env.client.post(
            s.env_path + "/finalize", headers=headers(s.auth, "seal", row["version"])
        )
    else:
        ref = row["board_id"]
        s.env_path = f"/v1/boards/{ref}"
        s.shape = {
            "id": str(uuid4()),
            "kind": "stroke",
            "points": [{"x": 5, "y": 6}, {"x": 7, "y": 8}],
        }
        s.operation = {
            "operation_id": str(uuid4()),
            "action": "put",
            "object_id": s.shape["id"],
            "shape": s.shape,
        }
        response = s.env.client.post(
            s.env_path + "/operations", headers=headers(s.auth, "op", 1), json=s.operation
        )
        assert response.status_code == 200, response.text
        row = response.json()
        response = s.env.client.post(
            s.env_path + "/seal", headers=headers(s.auth, "seal", row["version"])
        )
    assert response.status_code == 200, response.text
    return ref, response.json()


def submit(s, ref, row, key="submit"):
    return s.assessment.client.post(
        s.path + f"/stages/{s.stage_id}/submit",
        headers=headers(s.auth, key, 3),
        json={"workspace_id": ref, "snapshot_id": row["snapshot_id"]},
    )


def test_full_signed_submission_and_private_material(environment, token):
    s = environment
    ref, row = prepared(s)
    assert s.env.client.get(s.env_path, headers=token()).status_code == 404
    assert s.env.client.get(s.env_path, headers=token(roles=("employer",))).status_code == 403
    response = submit(s, ref, row)
    assert response.status_code == 200, response.text
    pinned = response.json()["progress"][0]
    assert response.json()["status"] == "submitted" and pinned["digest"] == row["digest"]
    assert (
        pinned["snapshot_id"] == row["snapshot_id"] and pinned["snapshot_version"] == row["version"]
    )
    assert submit(s, ref, row).json() == response.json()
    assert s.env.client.get(s.env_path, headers=s.auth).status_code == 200
    if s.name == "media":
        response = s.env.client.get(s.env_path + "/content", headers=s.auth)
        assert response.content == s.raw and response.headers["cache-control"] == "no-store"
        assert (
            s.env.client.post(
                s.env_path + "/finalize", headers=headers(s.auth, "late", row["version"])
            ).status_code
            == 409
        )
    else:
        assert (
            s.env.client.post(
                s.env_path + "/operations",
                headers=headers(s.auth, "late", row["version"]),
                json=s.operation,
            ).status_code
            == 409
        )
    with Session(s.env.app.state.engine) as db:
        caches = list(db.scalars(select(IdempotencyRecord)))
        assert all(
            "data_base64" not in item.response and '"points"' not in item.response
            for item in caches
        )
        assert all(
            all(isinstance(v, str) for v in item.envelope["payload"].values())
            for item in db.scalars(select(Outbox))
        )


def test_receipt_binding_replay_and_tampered_signature(environment):
    s = environment
    ref, row = prepared(s)
    body = SnapshotRequest(
        candidate_id=s.subject,
        session_id=s.session_id,
        stage_id=s.stage_id,
        workspace_id=ref,
        snapshot_id=row["snapshot_id"],
        requester="assessment",
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )
    raw = canonical(body)
    signature = sign(s.signatures["assessment"], SNAPSHOT_REQUEST, body)
    kwargs = {
        "content": raw,
        "headers": {"Content-Type": "application/json", "X-HR-Signature": signature},
    }
    response = s.env.client.post("/internal/v1/practical-receipt", **kwargs)
    assert response.status_code == 200 and response.json()["allowed"]
    assert "state" not in response.text and "data_base64" not in response.text
    assert s.env.client.post("/internal/v1/practical-receipt", **kwargs).status_code == 401
    kwargs["headers"]["X-HR-Signature"] = "invalid"
    assert s.env.client.post("/internal/v1/practical-receipt", **kwargs).status_code == 401
    with pytest.raises(HTTPException) as failure:
        s.receipt.fetch(
            s.subject,
            UUID(s.session_id),
            uuid4(),
            UUID(ref),
            UUID(row["snapshot_id"]),
            format=s.format,
        )
    assert failure.value.status_code == 409


def test_deadline_and_consent_withdrawal_close_every_access(environment):
    s = environment
    ref, row = prepared(s)
    with Session(s.assessment.app.state.engine) as db, db.begin():
        db.get(StageState, s.stage_id).deadline = datetime.now(UTC) - timedelta(seconds=1)
    assert submit(s, ref, row).status_code == 409
    with Session(s.privacy.app.state.engine) as db, db.begin():
        consent = db.scalar(
            select(ConsentRecord).where(
                ConsentRecord.candidate_id == str(s.subject),
                ConsentRecord.purpose == ("recording" if s.name == "media" else "assessment"),
            )
        )
        consent.status = "revoked"
    assert s.env.client.get(s.env_path, headers=s.auth).status_code == 409
    if s.name == "media":
        assert s.env.client.get(s.env_path + "/content", headers=s.auth).status_code == 409
    assert create(s, "retry").status_code == 409


def test_erasure_purges_bytes_history_caches_and_prevents_resurrection(environment):
    s = environment
    ref, row = prepared(s)
    from reverse_hr.platform.registry import domain_module

    domain = domain_module(s.name)
    event = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={"candidate_id": s.subject, "request_id": uuid4()},
    )
    event = event.model_copy(update={"aggregate_id": event.payload["request_id"]})
    with Session(s.env.app.state.engine) as db, db.begin():
        assert domain.process_deletion_request(db, event)
        assert not domain.process_deletion_request(db, event)
    with Session(s.env.app.state.engine) as db:
        models = (
            [Recording, RecordingChunk]
            if s.name == "media"
            else [Board, BoardOperation, BoardSnapshot]
        )
        assert all(not list(db.scalars(select(model))) for model in models)
        assert not list(db.scalars(select(IdempotencyRecord)))
        assert [r.envelope["event_type"] for r in db.scalars(select(Outbox))] == [
            s.name + ".data_deleted.v1"
        ]
    assert create(s, "resurrect").status_code == 409
    assert s.env.client.get(s.env_path, headers=s.auth).status_code == 409


def test_populated_downgrade_keeps_readiness(environment):
    s = environment
    prepared(s)
    with pytest.raises(RuntimeError, match="populated"):
        command.downgrade(migration_config(s.env.app.state.settings), "0001_transport")
    assert s.env.client.get("/health/ready").status_code == 200


def test_partial_retries_and_version_conflicts(environment):
    s = environment
    response = create(s)
    assert response.status_code == 201, response.text
    row = response.json()
    if s.name == "media":
        path = f"/v1/recordings/{row['recording_id']}"
        part = s.raw[:262144]
        body = {
            "data_base64": base64.b64encode(part).decode(),
            "digest": hashlib.sha256(part).hexdigest(),
        }
        response = s.env.client.put(
            path + "/chunks/0", headers=headers(s.auth, "part", 1), json=body
        )
        assert response.status_code == 200
        assert response.json()["received_chunks"] == [0]
        assert (
            s.env.client.put(
                path + "/chunks/0", headers=headers(s.auth, "other", 1), json=body
            ).status_code
            == 200
        )
        assert (
            s.env.client.post(path + "/finalize", headers=headers(s.auth, "missing", 2)).status_code
            == 409
        )
        body["digest"] = "0" * 64
        assert (
            s.env.client.put(
                path + "/chunks/0", headers=headers(s.auth, "bad", 2), json=body
            ).status_code
            == 422
        )
    else:
        path = f"/v1/boards/{row['board_id']}"
        shape = {
            "id": str(uuid4()),
            "kind": "text",
            "points": [{"x": 3, "y": 4}],
            "text": "Synthetic <script> text",
        }
        body = {
            "operation_id": str(uuid4()),
            "action": "put",
            "object_id": shape["id"],
            "shape": shape,
        }
        assert (
            s.env.client.post(
                path + "/operations", headers=headers(s.auth, "out-of-order", 2), json=body
            ).status_code
            == 409
        )
        response = s.env.client.post(
            path + "/operations", headers=headers(s.auth, "first", 1), json=body
        )
        assert response.status_code == 200, response.text
        assert (
            s.env.client.post(
                path + "/operations", headers=headers(s.auth, "duplicate", 1), json=body
            ).json()
            == response.json()
        )
        body["shape"]["text"] = "changed"
        assert (
            s.env.client.post(
                path + "/operations", headers=headers(s.auth, "conflict", 2), json=body
            ).status_code
            == 409
        )
        restored = s.env.client.get(path, headers=s.auth).json()
        assert restored["state"][0]["text"] == "Synthetic <script> text"


def test_corrupted_persisted_artifact_is_never_submitted(environment):
    s = environment
    ref, row = prepared(s)
    with Session(s.env.app.state.engine) as db, db.begin():
        if s.name == "media":
            part = db.get(RecordingChunk, (ref, 0))
            part.data = b"corrupt"
        else:
            snap = db.get(BoardSnapshot, row["snapshot_id"])
            snap.state = []
    assert submit(s, ref, row).status_code in {409, 503}
    with Session(s.assessment.app.state.engine) as db:
        assert db.get(StageState, s.stage_id).status == "active"


def test_permission_outage_never_replays_cached_artifact(environment, monkeypatch):
    s = environment
    prepared(s)
    from unittest.mock import Mock

    monkeypatch.setattr(
        s.env.app.state.processing_access, "check", Mock(side_effect=HTTPException(503))
    )
    assert create(s).status_code == 503
    assert s.env.client.get(s.env_path, headers=s.auth).status_code == 503


def test_recording_admission_and_browser_component_are_available(environment):
    s = environment
    response = s.env.client.get("/v1/environment.js")
    assert (
        response.status_code == 200
        and "mountRecording" in response.text
        and "mountBoard" in response.text
    )
    assert response.headers["cache-control"] == "no-store"
    if s.name == "media":
        body = {
            "session_id": s.session_id,
            "stage_id": s.stage_id,
            "recording_consent_id": s.recording_consent,
        }
        response = s.env.client.post("/v1/recordings/admission", headers=s.auth, json=body)
        assert response.status_code == 200 and response.json()["allowed"]
        with Session(s.privacy.app.state.engine) as db:
            body["recording_consent_id"] = db.scalar(
                select(ConsentRecord.consent_id).where(ConsentRecord.purpose == "assessment")
            )
        assert (
            s.env.client.post("/v1/recordings/admission", headers=s.auth, json=body).status_code
            == 409
        )


def test_evaluation_intake_waits_for_media_evidence_without_score(environment, service, token):
    from reverse_hr.protocols.evaluation_access import MaterialAccess
    from reverse_hr.services.evaluation.domain.evaluation import (
        EvaluationIntake,
        process_submission,
    )
    from reverse_hr.services.evaluation.evaluation_material import prepare_one

    s = environment
    ref, row = prepared(s)
    assert submit(s, ref, row).status_code == 200
    evaluation = service("evaluation")
    with Session(s.assessment.app.state.engine) as db:
        event = next(
            EventEnvelope.model_validate(r.envelope)
            for r in db.scalars(select(Outbox))
            if r.envelope["event_type"] == "assessment.stage_submitted.v1"
        )
    with Session(evaluation.app.state.engine) as db, db.begin():
        process_submission(db, event, evaluation.app.state.processing_access)
    access = MaterialAccess(evaluation.app.state.settings)
    access._signatures = s.signatures["evaluation"]

    def send(raw, signature):
        reply = s.assessment.client.post(
            "/internal/v1/evaluation-material",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        assert reply.status_code == 200, reply.text
        return reply.content, reply.headers["X-HR-Signature"]

    access.send_material = send
    access.check_assessment = lambda *_: None
    assert prepare_one(evaluation.app.state.engine, access)
    with Session(evaluation.app.state.engine) as db:
        row = db.get(EvaluationIntake, s.stage_id)
        assert row.status == "material_ready" and row.score is None and row.source is None
        assert row.material["task"]["format"] == s.format
    auth = token(roles=("assessment_reviewer",), amr=["mfa"])
    assert (
        evaluation.client.get(
            f"/v1/evaluation-reviews/stages/{s.stage_id}", headers=auth
        ).status_code
        == 409
    )


@pytest.mark.parametrize("name", ["media", "whiteboard"])
def test_empty_environment_migration_round_trip(service, name):
    target = service(name)
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0001_transport")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200
