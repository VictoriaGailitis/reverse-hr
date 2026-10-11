from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.snapshot_access import (
    SNAPSHOT_REQUEST,
    SNAPSHOT_RESPONSE,
    SnapshotAccess,
    SnapshotRequest,
)
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PracticalSession,
    StageState,
    process_deletion_request,
)
from reverse_hr.shared.db import IdempotencyRecord, Outbox
from reverse_hr.shared.signing import canonical, sign
from tests.services.coding_workspace.test_coding_workspace import create
from tests.services.coding_workspace.test_coding_workspace import (
    workspace_setup as workspace_setup_fixture,
)
from tests.shared.test_access import headers


@pytest.fixture
def setup(service, token):
    base = workspace_setup_fixture.__wrapped__(service, token)
    workspace, assessment, auth, subject, body, signatures = base
    workspace.app.state.workspace_signatures = signatures["coding-workspace"]
    access = SnapshotAccess(assessment.app.state.settings)
    access._signatures = signatures["assessment"]

    def send(payload, signature):
        reply = workspace.client.post(
            "/internal/v1/snapshot-receipt",
            content=payload,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    access.send_receipt = send
    assessment.app.state.snapshot_access = access
    snapshot = create(base)
    return base, snapshot, access


def session_path(setup):
    return f"/v1/assessment-sessions/{setup[0][4]['session_id']}"


def start(setup):
    base, _, _ = setup
    assessment, auth, body = base[1], base[2], base[4]
    path = session_path(setup)
    reply = assessment.client.post(path + "/start", headers=headers(auth, "start", 1))
    assert reply.status_code == 200, reply.text
    active = assessment.client.post(
        path + f"/stages/{body['stage_id']}/start", headers=headers(auth, "stage", 2)
    )
    assert active.status_code == 200, active.text
    return active.json()


def submit(setup, *, key="submit", version=3, snapshot=None, auth=None):
    base, pinned, _ = setup
    return base[1].client.post(
        session_path(setup) + f"/stages/{base[4]['stage_id']}/submit",
        headers=headers(auth or base[2], key, version),
        json={
            "workspace_id": pinned["workspace_id"],
            "snapshot_id": snapshot or pinned["snapshot_id"],
        },
    )


def test_full_code_session_pins_original_snapshot_and_closes_writes(setup, token):
    base, snapshot, _ = setup
    workspace, assessment, auth, _, _, _ = base
    initial = start(setup)
    assert initial["status"] == "in_progress" and initial["version"] == 3
    assert initial["progress"][0]["status"] == "active"
    assert initial["progress"][0]["deadline"].endswith("Z")
    changed = workspace.client.put(
        f"/v1/workspaces/{snapshot['workspace_id']}/files",
        headers=headers(auth, "save", 1),
        json={"files": [{"path": "main.py", "content": "later version"}]},
    )
    assert changed.status_code == 200
    finished = submit(setup)
    assert finished.status_code == 200, finished.text
    result = finished.json()
    assert (
        result["status"] == "submitted"
        and result["version"] == 4
        and result["current_stage_id"] is None
    )
    artifact = result["progress"][0]
    assert artifact["snapshot_id"] == snapshot["snapshot_id"] and artifact["snapshot_version"] == 1
    assert artifact["status"] == "submitted" and len(artifact["digest"]) == 64
    assert (
        "grade" not in result
        and "score" not in result
        and "Synthetic reference" not in finished.text
    )
    assert submit(setup).json() == result
    assert submit(setup, key="new").status_code == 409
    assert submit(setup, auth=token()).status_code == 404
    assert (
        assessment.client.post(
            session_path(setup) + "/start", headers=headers(auth, "start", 1)
        ).json()
        == result
    )
    assert (
        workspace.client.put(
            f"/v1/workspaces/{snapshot['workspace_id']}/files",
            headers=headers(auth, "blocked", 2),
            json={"files": [{"path": "main.py", "content": "bad"}]},
        ).status_code
        == 409
    )
    assert (
        workspace.client.get(
            f"/v1/workspaces/{snapshot['workspace_id']}/snapshots/{snapshot['snapshot_id']}",
            headers=auth,
        ).status_code
        == 200
    )
    assert (
        workspace.client.post(
            f"/v1/workspaces/{snapshot['workspace_id']}/runs",
            headers=headers(auth, "late-run"),
            json={"snapshot_id": snapshot["snapshot_id"]},
        ).status_code
        == 409
    )
    with Session(assessment.app.state.engine) as db:
        events = [
            row.envelope
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"].endswith("submitted.v1")
        ]
        assert len(events) == 2
        assert all(
            set(e["payload"])
            <= {
                "candidate_id",
                "session_id",
                "stage_id",
                "workspace_id",
                "snapshot_id",
                "plan_version_id",
            }
            for e in events
        )
        assert "later version" not in str(events)


def test_deadline_denies_edits_and_submission_without_changing_grade(setup):
    base, snapshot, _ = setup
    start(setup)
    with Session(base[1].app.state.engine) as db, db.begin():
        db.get(StageState, base[4]["stage_id"]).deadline = datetime.now(UTC) - timedelta(seconds=1)
    assert submit(setup).status_code == 409
    assert (
        base[0]
        .client.put(
            f"/v1/workspaces/{snapshot['workspace_id']}/files",
            headers=headers(base[2], "late", 1),
            json={"files": [{"path": "main.py", "content": "late"}]},
        )
        .status_code
        == 409
    )
    with Session(base[1].app.state.engine) as db:
        stage = db.get(StageState, base[4]["stage_id"])
        assert stage.status == "active" and stage.snapshot_id is None
        assert db.get(PracticalSession, base[4]["session_id"]).version == 3


def test_cancel_active_session_blocks_mutation_and_does_not_require_consent(setup, monkeypatch):
    base, _, _ = setup
    start(setup)
    monkeypatch.setattr(
        base[1].app.state.processing_access,
        "check_assessment",
        Mock(side_effect=HTTPException(409)),
    )
    reply = base[1].client.post(
        session_path(setup) + "/cancel", headers=headers(base[2], "cancel", 3)
    )
    assert reply.status_code == 200 and reply.json()["status"] == "cancelled"
    with Session(base[1].app.state.engine) as db:
        assert db.get(StageState, base[4]["stage_id"]).status == "cancelled"
    assert submit(setup).status_code == 409


@pytest.mark.parametrize("failure", [409, 503])
def test_receipt_denied_or_unavailable_rolls_back_submission(setup, monkeypatch, failure):
    base, _, access = setup
    start(setup)
    monkeypatch.setattr(access, "fetch", Mock(side_effect=HTTPException(failure)))
    assert submit(setup).status_code == failure
    with Session(base[1].app.state.engine) as db:
        assert db.get(StageState, base[4]["stage_id"]).status == "active"
        assert not list(
            db.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.operation.like("submit_stage:%"))
            )
        )


def test_final_event_failure_rolls_back_artifact_and_retry_uses_same_key(setup, monkeypatch):
    from reverse_hr.services.assessment.domain import assessment_lifecycle

    base, _, _ = setup
    start(setup)
    original = assessment_lifecycle.emit

    def emit(*args):
        if args[4] == "session_submitted":
            raise RuntimeError("synthetic failure")
        return original(*args)

    monkeypatch.setattr(assessment_lifecycle, "emit", emit)
    assert submit(setup).status_code == 500
    with Session(base[1].app.state.engine) as db:
        assert db.get(StageState, base[4]["stage_id"]).snapshot_id is None
        assert db.get(PracticalSession, base[4]["session_id"]).status == "in_progress"
    monkeypatch.setattr(assessment_lifecycle, "emit", original)
    assert submit(setup).status_code == 200


def test_snapshot_receipt_has_no_source_and_rejects_nonce_replay(setup):
    base, pinned, _ = setup
    body = SnapshotRequest(
        candidate_id=base[3],
        session_id=base[4]["session_id"],
        stage_id=base[4]["stage_id"],
        workspace_id=pinned["workspace_id"],
        snapshot_id=pinned["snapshot_id"],
        nonce=uuid4(),
        requester="assessment",
        issued_at=datetime.now(UTC),
    )
    auth = {
        "Content-Type": "application/json",
        "X-HR-Signature": sign(base[5]["assessment"], SNAPSHOT_REQUEST, body),
    }
    reply = base[0].client.post(
        "/internal/v1/snapshot-receipt", content=canonical(body), headers=auth
    )
    assert reply.status_code == 200 and reply.json()["allowed"]
    assert "files" not in reply.text and "synthetic" not in reply.text
    assert (
        base[0]
        .client.post("/internal/v1/snapshot-receipt", content=canonical(body), headers=auth)
        .status_code
        == 401
    )


@pytest.mark.parametrize(
    "field", ["candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id"]
)
def test_receipt_checks_every_ownership_and_source_binding(setup, field):
    base, pinned, access = setup
    values = dict(
        candidate_id=base[3],
        session_id=UUID(base[4]["session_id"]),
        stage_id=UUID(base[4]["stage_id"]),
        workspace_id=UUID(pinned["workspace_id"]),
        snapshot_id=UUID(pinned["snapshot_id"]),
    )
    values[field] = uuid4()
    with pytest.raises(HTTPException) as error:
        access.fetch(**values)
    assert error.value.status_code == 409


def test_signed_receipt_tampering_is_rejected(setup):
    base, _, access = setup
    original = access.send_receipt

    def tamper(body, signature):
        raw, signed = original(body, signature)
        return raw.replace(b'"snapshot_version":1', b'"snapshot_version":2'), signed

    access.send_receipt = tamper
    start(setup)
    assert submit(setup).status_code == 503


def test_receipt_source_format_is_checked(setup, monkeypatch):
    base, _, access = setup
    start(setup)
    original = access.send_receipt

    def changed(body, signature):
        from reverse_hr.protocols.snapshot_access import SnapshotReceipt

        raw, _ = original(body, signature)
        receipt = SnapshotReceipt.model_validate_json(raw).model_copy(update={"format": "sql"})
        return canonical(receipt), sign(base[5]["coding-workspace"], SNAPSHOT_RESPONSE, receipt)

    monkeypatch.setattr(access, "send_receipt", changed)
    assert submit(setup).status_code == 409


def test_deletion_erases_progress_and_pending_submission_events(setup):
    base, _, _ = setup
    start(setup)
    assert submit(setup).status_code == 200
    request_id = uuid4()
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": base[3], "request_id": request_id},
    )
    with Session(base[1].app.state.engine) as db, db.begin():
        process_deletion_request(db, event)
    with Session(base[1].app.state.engine) as db:
        assert not list(db.scalars(select(StageState)))
        assert db.get(PracticalSession, base[4]["session_id"]) is None
        assert not list(
            db.scalars(
                select(Outbox).where(
                    Outbox.envelope["event_type"].as_string() == "assessment.stage_submitted.v1"
                )
            )
        )
    assert submit(setup).status_code == 409


def test_populated_lifecycle_downgrade_keeps_readiness(setup):
    base, _, _ = setup
    start(setup)
    with pytest.raises(RuntimeError, match="populated assessment"):
        command.downgrade(migration_config(base[1].app.state.settings), "0004_assessment")
    assert base[1].client.get("/health/ready").status_code == 200


def test_sequential_code_and_sql_stages_cannot_be_skipped(setup, token):
    import copy

    from tests.services.assessment.test_assessment_content import PACKAGE
    from tests.services.assessment.test_assessment_sessions import make_session, plan

    base, _, _ = setup
    workspace, assessment, auth, subject, old_body, signatures = base
    assert (
        assessment.client.post(
            session_path(setup) + "/cancel", headers=headers(auth, "discard", 1)
        ).status_code
        == 200
    )
    package = copy.deepcopy(PACKAGE)
    sql = copy.deepcopy(package["tasks"][0])
    sql.update(key="second", format="sql", instruction="Synthetic SQL prompt")
    package["tasks"].append(sql)
    version, _, _ = plan(assessment, token, package)
    reply, _, _ = make_session(assessment, token, version, subject, key="second-session")
    assert reply.status_code == 201
    stages = reply.json()["stages"]
    body = dict(old_body, session_id=reply.json()["session_id"], stage_id=stages[0]["stage_id"])
    new_base = workspace, assessment, auth, subject, body, signatures
    created = workspace.client.post(
        "/v1/workspaces", headers=headers(auth, "next-code-workspace"), json=body
    )
    assert created.status_code == 201, created.text
    new_setup = new_base, created.json(), setup[2]
    path = session_path(new_setup)
    session = assessment.client.post(path + "/start", headers=headers(auth, "new-start", 1)).json()
    assert [p["status"] for p in session["progress"]] == ["pending", "pending"]
    assert (
        assessment.client.post(
            path + f"/stages/{stages[1]['stage_id']}/start", headers=headers(auth, "skip", 2)
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            path + f"/stages/{stages[0]['stage_id']}/start", headers=headers(auth, "first", 2)
        ).status_code
        == 200
    )
    submitted = submit(new_setup)
    assert submitted.status_code == 200 and submitted.json()["status"] == "in_progress"
    assert submitted.json()["current_stage_id"] == stages[1]["stage_id"]
    assert (
        assessment.client.post(
            path + f"/stages/{stages[1]['stage_id']}/start", headers=headers(auth, "second", 4)
        ).status_code
        == 200
    )
    second_body = dict(
        body, stage_id=stages[1]["stage_id"], files=[{"path": "query.sql", "content": "SELECT 1;"}]
    )
    snapshot = workspace.client.post(
        "/v1/workspaces", headers=headers(auth, "sql-workspace"), json=second_body
    )
    assert snapshot.status_code == 201, snapshot.text
    final = assessment.client.post(
        path + f"/stages/{stages[1]['stage_id']}/submit",
        headers=headers(auth, "sql-submit", 5),
        json={
            "workspace_id": snapshot.json()["workspace_id"],
            "snapshot_id": snapshot.json()["snapshot_id"],
        },
    )
    assert final.status_code == 200 and final.json()["status"] == "submitted"
    assert final.json()["version"] == 6
    assert [p["status"] for p in final.json()["progress"]] == ["submitted", "submitted"]


def test_active_session_prevents_second_preflight_and_preserves_start_timer(setup):
    base, _, _ = setup
    active = start(setup)
    original = base[1].client.get(session_path(setup), headers=base[2]).json()
    reply = base[1].client.post(
        "/v1/assessment-sessions",
        headers=headers(base[2], "duplicate-session"),
        json={
            "plan_version_id": original["plan_version_id"],
            "assessment_consent_id": str(uuid4()),
        },
    )
    assert reply.status_code == 409
    replay = base[1].client.post(
        session_path(setup) + f"/stages/{base[4]['stage_id']}/start",
        headers=headers(base[2], "stage", 2),
    )
    assert (
        replay.status_code == 200
        and replay.json()["progress"][0]["deadline"] == active["progress"][0]["deadline"]
    )


def test_deadline_rechecked_after_remote_receipt(setup, monkeypatch):
    from types import SimpleNamespace

    from reverse_hr.services.assessment.domain import assessment_lifecycle

    base, _, access = setup
    start(setup)
    future = [False]
    real_now = datetime.now
    monkeypatch.setattr(
        assessment_lifecycle,
        "datetime",
        SimpleNamespace(
            now=lambda zone: real_now(zone) + (timedelta(hours=1) if future[0] else timedelta())
        ),
    )
    original = access.fetch

    def slow(*args):
        receipt = original(*args)
        future[0] = True
        return receipt

    monkeypatch.setattr(access, "fetch", slow)
    assert submit(setup).status_code == 409
    with Session(base[1].app.state.engine) as db:
        assert db.get(StageState, base[4]["stage_id"]).snapshot_id is None


def test_start_and_replay_recheck_consent(setup, monkeypatch):
    base, _, _ = setup
    start(setup)
    monkeypatch.setattr(
        base[1].app.state.processing_access,
        "check_assessment",
        Mock(side_effect=HTTPException(409)),
    )
    assert (
        base[1]
        .client.post(session_path(setup) + "/start", headers=headers(base[2], "start", 1))
        .status_code
        == 409
    )
    assert submit(setup).status_code == 409


def test_receipt_context_and_freshness_are_verified(setup):
    base, pinned, _ = setup
    body = SnapshotRequest(
        candidate_id=base[3],
        session_id=base[4]["session_id"],
        stage_id=base[4]["stage_id"],
        workspace_id=pinned["workspace_id"],
        snapshot_id=pinned["snapshot_id"],
        nonce=uuid4(),
        requester="assessment",
        issued_at=datetime.now(UTC),
    )
    for candidate, context in (
        (body, SNAPSHOT_RESPONSE),
        (
            body.model_copy(update={"issued_at": datetime.now(UTC) - timedelta(minutes=5)}),
            SNAPSHOT_REQUEST,
        ),
    ):
        reply = base[0].client.post(
            "/internal/v1/snapshot-receipt",
            content=canonical(candidate),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": sign(base[5]["assessment"], context, candidate),
            },
        )
        assert reply.status_code == 401


def test_client_cannot_set_artifact_digest_or_change_stage_order(setup):
    base, pinned, _ = setup
    start(setup)
    reply = base[1].client.post(
        session_path(setup) + f"/stages/{base[4]['stage_id']}/submit",
        headers=headers(base[2], "forged", 3),
        json={
            "workspace_id": pinned["workspace_id"],
            "snapshot_id": pinned["snapshot_id"],
            "digest": "0" * 64,
        },
    )
    assert reply.status_code == 422
    assert (
        base[1]
        .client.post(
            session_path(setup) + f"/stages/{uuid4()}/start",
            headers=headers(base[2], "foreign-stage", 3),
        )
        .status_code
        == 409
    )


def test_stage_read_permission_cannot_be_reused_as_write_permission(setup):
    from reverse_hr.protocols.stage_access import STAGE_REQUEST_CONTEXT, StageRequest

    base, _, _ = setup
    start(setup)
    assert submit(setup).status_code == 200
    body = StageRequest(
        candidate_id=base[3],
        session_id=base[4]["session_id"],
        stage_id=base[4]["stage_id"],
        requester="coding-workspace",
        purpose="read",
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )
    signature = sign(base[5]["coding-workspace"], STAGE_REQUEST_CONTEXT, body)
    reply = base[1].client.post(
        "/internal/v1/workspace-stage",
        content=canonical(body),
        headers={"Content-Type": "application/json", "X-HR-Signature": signature},
    )
    assert reply.status_code == 200 and reply.json()["allowed"]
    changed = body.model_copy(update={"purpose": "write"})
    replay = base[1].client.post(
        "/internal/v1/workspace-stage",
        content=canonical(changed),
        headers={"Content-Type": "application/json", "X-HR-Signature": signature},
    )
    assert replay.status_code == 401


def test_voice_stage_starts_with_server_deadline(setup, token):
    import copy

    from tests.services.assessment.test_assessment_content import PACKAGE
    from tests.services.assessment.test_assessment_sessions import make_session, plan

    base, _, _ = setup
    assert (
        base[1]
        .client.post(
            session_path(setup) + "/cancel", headers=headers(base[2], "cancel-original", 1)
        )
        .status_code
        == 200
    )
    package = copy.deepcopy(PACKAGE)
    package["tasks"][0]["format"] = "voice"
    package["tasks"][0]["rubric"][0]["evidence"] = "timestamped_recording"
    version, _, _ = plan(base[1], token, package)
    reply, _, _ = make_session(base[1], token, version, base[3], key="voice-session")
    assert reply.status_code == 201
    path = f"/v1/assessment-sessions/{reply.json()['session_id']}"
    assert (
        base[1].client.post(path + "/start", headers=headers(base[2], "voice-start", 1)).status_code
        == 200
    )
    stage_id = reply.json()["stages"][0]["stage_id"]
    assert (
        base[1]
        .client.post(path + f"/stages/{stage_id}/start", headers=headers(base[2], "voice-stage", 2))
        .status_code
        == 200
    )
    with Session(base[1].app.state.engine) as db:
        stage = db.get(StageState, stage_id)
        assert (
            stage.status == "active" and stage.started_at is not None and stage.deadline is not None
        )


def test_workspace_processing_denial_never_returns_artifact_metadata(setup, monkeypatch):
    base, pinned, access = setup
    monkeypatch.setattr(
        base[0].app.state.processing_access, "check", Mock(side_effect=HTTPException(409))
    )
    with pytest.raises(HTTPException) as error:
        access.fetch(
            base[3],
            UUID(base[4]["session_id"]),
            UUID(base[4]["stage_id"]),
            UUID(pinned["workspace_id"]),
            UUID(pinned["snapshot_id"]),
        )
    assert error.value.status_code == 409


def test_finished_stage_allows_historical_run_reads_but_denies_execution(setup):
    from reverse_hr.protocols.runner_exchange import MANIFEST_REQUEST, ManifestRequest

    base, pinned, _ = setup
    start(setup)
    run = base[0].client.post(
        f"/v1/workspaces/{pinned['workspace_id']}/runs",
        headers=headers(base[2], "run"),
        json={"snapshot_id": pinned["snapshot_id"]},
    )
    assert run.status_code == 202
    assert submit(setup).status_code == 200
    for purpose in ("read", "write"):
        body = ManifestRequest(
            candidate_id=base[3],
            run_id=run.json()["run_id"],
            workspace_id=pinned["workspace_id"],
            snapshot_id=pinned["snapshot_id"],
            purpose=purpose,
            requester="code-runner",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        reply = base[0].client.post(
            "/internal/v1/run-manifest",
            content=canonical(body),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": sign(base[5]["code-runner"], MANIFEST_REQUEST, body),
            },
        )
        assert reply.status_code == 200
        assert reply.json()["allowed"] == (purpose == "read")
        assert (reply.json()["manifest"] is not None) == (purpose == "read")
