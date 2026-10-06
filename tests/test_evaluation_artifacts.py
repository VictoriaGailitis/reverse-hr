from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_evaluation_material import deletion
from test_evaluation_material import setup as material_setup
from test_event_transport import signatures as signatures_fixture

from reverse_hr.db import Outbox
from reverse_hr.domains.coding_workspace import Snapshot
from reverse_hr.domains.evaluation import EvaluationIntake, process_deletion_request
from reverse_hr.evaluation_access import MATERIAL_REQUEST
from reverse_hr.evaluation_artifact_access import (
    ARTIFACT_REQUEST,
    ARTIFACT_RESPONSE,
    MAX_ARTIFACT_BYTES,
    ArtifactAccess,
    ArtifactPermitAccess,
    ArtifactReceipt,
    ArtifactRequest,
)
from reverse_hr.evaluation_artifacts import collect_one
from reverse_hr.evaluation_material import prepare_one
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import canonical, sign

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures):
    base = material_setup.__wrapped__(service, token, signatures)
    target, assessment, event, material_access, lifecycle = base
    assert prepare_one(target.app.state.engine, material_access)
    workspace = lifecycle[0][0]
    workspace.app.state.workspace_signatures = signatures["coding-workspace"]
    permit_access = ArtifactPermitAccess(workspace.app.state.settings)
    permit_access._signatures = signatures["coding-workspace"]

    def send_permit(raw, signed):
        reply = assessment.client.post(
            "/internal/v1/evaluation-artifact-admission",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signed},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    permit_access.send_permit = send_permit
    workspace.app.state.artifact_permit_access = permit_access
    artifact_access = ArtifactAccess(target.app.state.settings)
    artifact_access._signatures = signatures["evaluation"]

    def send_artifact(raw, signed):
        reply = workspace.client.post(
            "/internal/v1/evaluation-artifact",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signed},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    artifact_access.send_artifact = send_artifact
    return base, workspace, artifact_access


def intake(setup):
    with Session(setup[0][0].app.state.engine) as session:
        return session.get(EvaluationIntake, str(setup[0][2].aggregate_id))


def refs(setup):
    row = intake(setup)
    return setup[0][2].payload | {
        "format": row.material["task"]["format"],
        "snapshot_version": row.material["snapshot_version"],
        "digest": row.material["snapshot_digest"],
    }


def collect(setup, **kwargs):
    return collect_one(setup[0][0].app.state.engine, setup[0][3], setup[2], **kwargs)


def test_source_collected_with_pending_requirements_private_status(setup):
    assert collect(setup)
    assert not collect(setup)
    row = intake(setup)
    assert row.status == "artifact_ready" and row.version == 3 and row.artifact_attempts == 1
    assert row.source["files"] == setup[0][4][1]["files"]
    assert len(row.requirements) == len(row.material["task"]["rubric"])
    assert all(r["status"] == "pending" and r["points"] is None for r in row.requirements)
    assert all(r["digest"] == row.material["snapshot_digest"] for r in row.requirements)
    assert all(r["snapshot_id"] == row.snapshot_id for r in row.requirements)
    target, _, event, _, lifecycle = setup[0]
    reply = target.client.get(
        f"/v1/evaluations/stages/{event.aggregate_id}", headers=lifecycle[0][2]
    )
    assert reply.status_code == 200 and reply.json()["score"] is None
    assert (
        "files" not in reply.text
        and "requirements" not in reply.text
        and "rubric" not in reply.text
    )
    with Session(target.app.state.engine) as session:
        events = list(session.scalars(select(Outbox)))
        assert len(events) == 3
        artifact = next(
            r.envelope for r in events if r.envelope["event_type"] == "evaluation.artifact_ready.v1"
        )
        assert artifact["aggregate_version"] == 3 and set(artifact["payload"]) == set(event.payload)


@pytest.mark.parametrize(
    "key",
    [
        "candidate_id",
        "session_id",
        "stage_id",
        "workspace_id",
        "snapshot_id",
        "snapshot_version",
        "digest",
        "format",
    ],
)
def test_mismatched_refs_and_pins_denied(setup, key):
    changes = {"snapshot_version": 2, "digest": "f" * 64, "format": "sql"}
    request = refs(setup) | {key: changes.get(key, uuid4())}
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**request)
    assert exc.value.status_code == 409
    assert intake(setup).source is None


def test_artifact_request_nonce_context_and_freshness(setup):
    workspace, access = setup[1], setup[2]
    body = ArtifactRequest(
        **refs(setup), requester="evaluation", nonce=uuid4(), issued_at=datetime.now(UTC)
    )
    path = "/internal/v1/evaluation-artifact"
    headers = {
        "Content-Type": "application/json",
        "X-HR-Signature": sign(access.signatures, ARTIFACT_REQUEST, body),
    }
    first = workspace.client.post(path, content=canonical(body), headers=headers)
    assert first.status_code == 200 and first.json()["allowed"]
    assert workspace.client.post(path, content=canonical(body), headers=headers).status_code == 401
    headers["X-HR-Signature"] = sign(access.signatures, MATERIAL_REQUEST, body)
    assert workspace.client.post(path, content=canonical(body), headers=headers).status_code == 401
    old = body.model_copy(
        update={"nonce": uuid4(), "issued_at": datetime.now(UTC) - timedelta(minutes=1)}
    )
    headers["X-HR-Signature"] = sign(access.signatures, ARTIFACT_REQUEST, old)
    assert workspace.client.post(path, content=canonical(old), headers=headers).status_code == 401


@pytest.mark.parametrize("mode", ["nonce", "version", "digest", "tamper", "oversize", "manifest"])
def test_bad_signed_or_tampered_artifact_fails_closed(setup, mode):
    access = setup[2]
    original = access.send_artifact

    def corrupt(raw, signed):
        reply, signature = original(raw, signed)
        if mode == "tamper":
            return reply + b" ", signature
        if mode == "oversize":
            return b"x" * (MAX_ARTIFACT_BYTES + 1), signature
        receipt = ArtifactReceipt.model_validate_json(reply)
        if mode == "nonce":
            receipt = receipt.model_copy(update={"nonce": uuid4()})
        elif mode == "version":
            receipt = receipt.model_copy(update={"snapshot_version": receipt.snapshot_version + 1})
        elif mode == "digest":
            receipt = receipt.model_copy(update={"digest": "f" * 64})
        else:
            receipt.manifest.files[0].content += "changed"
        return canonical(receipt), sign(
            setup[1].app.state.workspace_signatures, ARTIFACT_RESPONSE, receipt
        )

    access.send_artifact = corrupt
    with pytest.raises(HTTPException) as exc:
        access.fetch(**refs(setup))
    assert exc.value.status_code == 503
    assert collect(setup) and intake(setup).status == "artifact_retry"
    assert intake(setup).source is None and intake(setup).requirements is None


def test_assessment_permit_denial_returns_no_source(setup):
    setup[0][1].app.state.processing_access.check_assessment = Mock(side_effect=HTTPException(409))
    body = ArtifactRequest(
        **refs(setup), requester="evaluation", nonce=uuid4(), issued_at=datetime.now(UTC)
    )
    raw, _ = setup[2].send_artifact(
        canonical(body), sign(setup[2].signatures, ARTIFACT_REQUEST, body)
    )
    receipt = ArtifactReceipt.model_validate_json(raw)
    assert not receipt.allowed and receipt.manifest is None


def test_tampered_permit_never_releases_source(setup):
    permit = setup[1].app.state.artifact_permit_access
    original = permit.send_permit
    permit.send_permit = lambda *args: (original(*args)[0] + b" ", "invalid")
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**refs(setup))
    assert exc.value.status_code == 503


def test_workspace_corruption_fails_digest_validation(setup):
    with Session(setup[1].app.state.engine) as session, session.begin():
        row = session.get(Snapshot, str(setup[0][2].payload["snapshot_id"]))
        row.files = [{"path": "main.py", "content": "unexpected source"}]
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**refs(setup))
    assert exc.value.status_code == 503


@pytest.mark.parametrize("code", [409, 503])
def test_workspace_processing_deny_or_unavailable_no_source(setup, code):
    setup[1].app.state.processing_access.check = Mock(side_effect=HTTPException(code))
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**refs(setup))
    assert exc.value.status_code == code
    assert collect(setup)
    assert intake(setup).status == ("artifact_blocked" if code == 409 else "artifact_retry")
    assert intake(setup).source is None


def test_bounded_artifact_retries_and_no_score(setup):
    setup[2].fetch = Mock(side_effect=HTTPException(503))
    now = datetime.now(UTC)
    assert collect(setup, now=now, max_attempts=2)
    assert not collect(setup, now=now, max_attempts=2)
    assert collect(setup, now=now + timedelta(seconds=6), max_attempts=2)
    assert intake(setup).status == "artifact_unavailable"
    assert intake(setup).artifact_attempts == 2 and intake(setup).source is None
    assert not collect(setup, now=now + timedelta(hours=1))


def test_outbox_failure_rolls_back_source_requirements_and_attempt(setup, monkeypatch):
    from reverse_hr import evaluation_artifacts

    original = evaluation_artifacts.enqueue
    monkeypatch.setattr(evaluation_artifacts, "enqueue", Mock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        collect(setup)
    assert intake(setup).source is None and intake(setup).requirements is None
    assert intake(setup).version == 2 and intake(setup).artifact_attempts == 0
    monkeypatch.setattr(evaluation_artifacts, "enqueue", original)
    assert collect(setup)


def test_delete_during_fetch_and_after_collection_no_source_revival(setup):
    target, _, event, _, _ = setup[0]
    original = setup[2].fetch

    def fetch_then_delete(**kwargs):
        source = original(**kwargs)
        with Session(target.app.state.engine) as session, session.begin():
            process_deletion_request(session, deletion(event))
        return source

    setup[2].fetch = fetch_then_delete
    assert collect(setup)
    assert intake(setup) is None
    with Session(target.app.state.engine) as session:
        assert [r.envelope["event_type"] for r in session.scalars(select(Outbox))] == [
            "evaluation.data_deleted.v1"
        ]


def test_source_deletion_cleans_business_events_and_protected_downgrade(setup):
    target, _, event, _, _ = setup[0]
    assert collect(setup)
    with pytest.raises(RuntimeError, match="populated Evaluation"):
        command.downgrade(migration_config(target.app.state.settings), "0003_evaluation")
    assert target.client.get("/health/ready").status_code == 200
    with pytest.raises(RuntimeError, match="populated workspaces"):
        command.downgrade(migration_config(setup[1].app.state.settings), "0004_workspace")
    assert setup[1].client.get("/health/ready").status_code == 200
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(event))
    assert intake(setup) is None
    with Session(target.app.state.engine) as session:
        assert [r.envelope["event_type"] for r in session.scalars(select(Outbox))] == [
            "evaluation.data_deleted.v1"
        ]


def test_permission_withdrawn_after_source_not_persisted(setup):
    setup[0][3].check_assessment = Mock(side_effect=HTTPException(409))
    assert collect(setup)
    assert intake(setup).status == "artifact_blocked" and intake(setup).source is None


def test_workspace_deletion_during_admission_rechecks_local_state(setup):
    from reverse_hr.domains.coding_workspace import process_deletion_request as erase

    permit = setup[1].app.state.artifact_permit_access
    original = permit.check

    def check_then_delete(body):
        result = original(body)
        with Session(setup[1].app.state.engine) as session, session.begin():
            erase(session, deletion(setup[0][2]))
        return result

    permit.check = check_then_delete
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**refs(setup))
    assert exc.value.status_code == 409


def test_overlapping_collection_commits_one_source_event(setup):
    original = setup[2].fetch
    entered = False

    def overlapping(**kwargs):
        nonlocal entered
        source = original(**kwargs)
        if not entered:
            entered = True
            assert collect(setup)
        return source

    setup[2].fetch = overlapping
    assert collect(setup)
    assert intake(setup).artifact_attempts == 1 and intake(setup).version == 3
    with Session(setup[0][0].app.state.engine) as session:
        assert (
            sum(
                r.envelope["event_type"] == "evaluation.artifact_ready.v1"
                for r in session.scalars(select(Outbox))
            )
            == 1
        )


def test_real_privacy_consent_revoke_blocks_source_and_status(setup, service, token, signatures):
    from test_access import headers
    from test_processing_access import connect_access

    from reverse_hr.domains.privacy import ConsentRecord
    from reverse_hr.evaluation_access import MaterialAccess

    target, assessment, event, material_access, lifecycle = setup[0]
    privacy = service("privacy")
    privacy.app.state.privacy_signatures = signatures["privacy"]
    # The fixture's session has a synthetic consent UUID; seed its real Privacy record.
    with Session(privacy.app.state.engine) as session, session.begin():
        session.add(
            ConsentRecord(
                consent_id=intake(setup).material["consent_id"],
                candidate_id=str(event.payload["candidate_id"]),
                purpose="assessment",
                document_version="demo-v1",
                status="active",
                version=1,
                granted_at=datetime.now(UTC),
            )
        )

    def permission(raw, signed):
        reply = privacy.client.post(
            "/internal/v1/assessment-permission",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signed},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    for name, app in (
        ("evaluation", target.app),
        ("assessment", assessment.app),
        ("coding-workspace", setup[1].app),
    ):
        app.state.processing_access = connect_access(name, privacy, signatures)
        app.state.processing_access.send_assessment = permission
    material_access.send_assessment = permission
    material_access.check_assessment = MaterialAccess.check_assessment.__get__(material_access)
    assert collect(setup)
    consent_id = intake(setup).material["consent_id"]
    auth = token(event.payload["candidate_id"])
    assert (
        privacy.client.post(
            f"/v1/consents/{consent_id}/revoke",
            headers=headers(auth, "revoke", 1),
        ).status_code
        == 200
    )
    assert (
        target.client.get(
            f"/v1/evaluations/stages/{event.aggregate_id}", headers=lifecycle[0][2]
        ).status_code
        == 409
    )
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**refs(setup))
    assert exc.value.status_code == 409


def test_existing_different_snapshot_is_not_the_submitted_artifact(setup):
    other_id = uuid4()
    with Session(setup[1].app.state.engine) as session, session.begin():
        original = session.get(Snapshot, str(setup[0][2].payload["snapshot_id"]))
        session.add(
            Snapshot(
                snapshot_id=str(other_id),
                workspace_id=original.workspace_id,
                version=2,
                files=original.files,
                digest=original.digest,
                created_at=datetime.now(UTC),
            )
        )
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**(refs(setup) | {"snapshot_id": other_id, "snapshot_version": 2}))
    assert exc.value.status_code == 409


def test_correctly_signed_permit_with_wrong_nonce_rejected(setup):
    from reverse_hr.evaluation_artifact_access import PERMIT_RESPONSE, ArtifactPermit

    access = setup[1].app.state.artifact_permit_access
    original = access.send_permit

    def misbound(*args):
        raw, _ = original(*args)
        status = ArtifactPermit.model_validate_json(raw).model_copy(update={"nonce": uuid4()})
        return canonical(status), sign(
            setup[0][1].app.state.assessment_signatures, PERMIT_RESPONSE, status
        )

    access.send_permit = misbound
    with pytest.raises(HTTPException) as exc:
        setup[2].fetch(**refs(setup))
    assert exc.value.status_code == 503


def test_changed_private_rubric_pin_cannot_collect_source(setup):
    with Session(setup[0][0].app.state.engine) as session, session.begin():
        row = session.get(EvaluationIntake, str(setup[0][2].aggregate_id))
        row.material = row.material | {"content_digest": "f" * 64}
    setup[2].fetch = Mock(side_effect=AssertionError("Source must not be fetched with stale pins"))
    assert collect(setup)
    assert intake(setup).status == "artifact_retry" and intake(setup).source is None
