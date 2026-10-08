"""Integrity telemetry is bounded, consent fenced, immutable and independent of scores."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_event_transport import signatures as signatures_fixture

from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.proctoring import (
    ClientStream,
    IntegrityReview,
    IntegrityTrack,
    ProctorEvent,
    ProctorSubject,
    process_deletion_request,
    process_environment_event,
)
from reverse_hr.event_transport import InvalidEvent, ProctoringConsumer
from reverse_hr.events import EventEnvelope
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import canonical, sign
from reverse_hr.proctoring_access import REQUEST, IntegrityAccess, IntegrityRequest

signatures = signatures_fixture


@pytest.fixture
def env(service, token):
    s = SimpleNamespace(
        env=service("proctoring"),
        subject=uuid4(),
        session_id=uuid4(),
        stage_id=uuid4(),
        closed=False,
        denied=False,
    )
    s.auth = token(s.subject)
    s.reviewer = token(roles=("assessment_reviewer",), amr=["mfa"])

    def stage(candidate, session_id, stage_id, purpose="write"):
        if (
            s.denied
            or (candidate, session_id, stage_id) != (s.subject, s.session_id, s.stage_id)
            or (purpose == "write" and s.closed)
        ):
            raise HTTPException(409)
        return "whiteboard"

    s.env.app.state.stage_access = SimpleNamespace(check_stage=stage)
    s.body = dict(
        session_id=str(s.session_id),
        stage_id=str(s.stage_id),
        stream_id=str(uuid4()),
        client_started_at=datetime.now(UTC).isoformat(),
    )
    s.path = f"/v1/proctoring/candidates/{s.subject}/sessions/{s.session_id}/stages/{s.stage_id}"
    return s


def create(s, **changes):
    reply = s.env.client.post(
        "/v1/proctoring/streams", headers=headers(s.auth, "create"), json=s.body | changes
    )
    assert reply.status_code == 201, reply.text
    return reply.json()


def event(s, seq, kind="heartbeat", **changes):
    start = datetime.fromisoformat(s.body["client_started_at"])
    return (
        dict(
            event_id=str(uuid4()),
            sequence=seq,
            kind=kind,
            client_time=(start + timedelta(milliseconds=seq)).isoformat(),
            elapsed_ms=seq,
        )
        | changes
    )


def ingest(s, events, key=None):
    return s.env.client.post(
        f"/v1/proctoring/streams/{s.body['stream_id']}/events",
        headers=headers(s.auth, key or str(uuid4())),
        json={"events": events},
    )


def state(s, auth=None, **params):
    reply = s.env.client.get(s.path, headers=auth or s.reviewer, params=params)
    assert reply.status_code == 200, reply.text
    return reply.json()


def decide(s, outcome="inconclusive", evidence_ids=None, **changes):
    summary = state(s)["summary"]
    body = {k: summary[k] for k in ("timeline_version", "evidence_digest")}
    body |= {
        "outcome": outcome,
        "reason": "Human considered technical uncertainty",
        "evidence_ids": evidence_ids or [],
    }
    return s.env.client.post(
        s.path + "/reviews",
        headers=headers(s.reviewer, str(uuid4()), summary["version"]),
        json=body | changes,
    )


def deletion(subject):
    request = uuid4()
    return EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request},
    )


def test_out_of_order_gap_fill_replay_conflict_and_atomic_batch(env):
    s = env
    create(s)
    first, third = event(s, 1, "focus_lost"), event(s, 3, "paste")
    assert ingest(s, [third, first]).status_code == 200
    view = state(s)
    assert view["summary"]["status"] == "needs_review"
    assert view["summary"]["gaps"] == {s.body["stream_id"]: [[2, 2]]}
    assert "attention_required" in view["summary"]["flags"]
    assert [e["sequence"] for e in view["events"]] == [3, 1]  # authoritative arrival order
    assert ingest(s, [first, third]).json()["timeline_version"] == 2
    second = event(s, 2)
    assert ingest(s, [second]).status_code == 200
    assert state(s)["summary"]["gaps"] == {}
    assert ingest(s, [first | {"kind": "paste"}]).status_code == 409
    assert ingest(s, [event(s, 4), third | {"event_id": str(uuid4())}]).status_code == 409
    assert state(s)["summary"]["timeline_version"] == 3
    page = state(s, limit=2)
    assert page["next_after"] == 2
    assert len(state(s, after=page["next_after"])["events"]) == 1


def test_review_is_human_evidence_bound_and_new_evidence_invalidates_it(env):
    s = env
    create(s)
    e = event(s, 1, "paste")
    ingest(s, [e])
    assert decide(s, "concern").status_code == 422
    assert decide(s, "concern", [str(uuid4())]).status_code == 422
    assert decide(s, "concern", [e["event_id"]], evidence_digest="0" * 64).status_code == 409
    reply = decide(s, "concern", [e["event_id"]])
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "concern"
    assert reply.json()["client_telemetry_trusted"] is False
    ingest(s, [event(s, 2, "recording_error")])
    view = state(s)["summary"]
    assert view["status"] == "needs_review" and view["latest_review"]["outcome"] == "concern"
    assert "technical_issue" in view["flags"]
    assert decide(s, "clear").json()["status"] == "clear"
    with Session(s.env.app.state.engine) as session:
        assert len(list(session.scalars(select(IntegrityReview)))) == 2
        assert {o.envelope["event_type"] for o in session.scalars(select(Outbox))} == {
            "proctoring.integrity_reviewed.v1"
        }


def test_new_stream_invalidates_review_without_overwriting_old_material(env):
    s = env
    create(s)
    ingest(s, [event(s, 1)])
    assert decide(s, "clear").status_code == 200
    old = s.body.copy()
    s.body["stream_id"] = str(uuid4())
    reply = s.env.client.post(
        "/v1/proctoring/streams", headers=headers(s.auth, "second-stream"), json=s.body
    )
    assert reply.status_code == 201
    assert state(s)["summary"]["status"] == "needs_review"
    assert state(s)["events"][0]["stream_id"] == old["stream_id"]


def test_clock_and_missing_heartbeat_are_uncertainty_not_guilt(env):
    s = env
    create(s)
    ingest(
        s,
        [
            event(s, 1),
            event(
                s,
                3,
                "offline",
                elapsed_ms=100000,
                client_time=(datetime.now(UTC) + timedelta(minutes=3)).isoformat(),
            ),
        ],
    )
    summary = state(s)["summary"]
    assert {
        "sequence_gap",
        "telemetry_time_gap",
        "client_time_future",
        "client_clock_discontinuity",
        "technical_issue",
    } <= set(summary["flags"])
    assert summary["status"] == "needs_review"
    assert summary["latest_review"] is None


def test_late_delivery_recovery_and_no_new_stream_after_closed(env):
    s = env
    create(s)
    s.closed = True
    assert ingest(s, [event(s, 1)]).status_code == 200
    assert "late_client_delivery" in state(s)["events"][0]["flags"]
    assert (
        s.env.client.post(
            "/v1/proctoring/streams", headers=headers(s.auth, "retry-create"), json=s.body
        ).status_code
        == 201
    )
    assert (
        s.env.client.post(
            "/v1/proctoring/streams",
            headers=headers(s.auth, "new"),
            json=s.body | {"stream_id": str(uuid4())},
        ).status_code
        == 409
    )
    s.denied = True
    assert ingest(s, [event(s, 2)]).status_code == 409
    assert s.env.client.get(s.path, headers=s.reviewer).status_code == 409


@pytest.mark.parametrize(
    "change",
    [
        {"sequence": True},
        {"sequence": 0},
        {"kind": "ai_detected"},
        {"client_time": "2026-10-09T12:00:00"},
        {"clipboard": "private content"},
        {"elapsed_ms": -1},
    ],
)
def test_invalid_telemetry_rejected_without_storing_content(env, change):
    s = env
    create(s)
    assert ingest(s, [event(s, 1) | change]).status_code == 422
    with Session(s.env.app.state.engine) as session:
        assert not list(session.scalars(select(ProctorEvent)))


def test_ownership_role_mfa_and_self_review(env, token):
    s = env
    create(s)
    ingest(s, [event(s, 1)])
    assert s.env.client.get(s.path, headers=token(roles=("employer",))).status_code == 403
    assert (
        s.env.client.get(s.path, headers=token(roles=("assessment_reviewer",))).status_code == 403
    )
    assert (
        s.env.client.get(
            s.path, headers=token(s.subject, roles=("assessment_reviewer",), amr=["mfa"])
        ).status_code
        == 403
    )
    other = token()
    assert (
        s.env.client.get(f"/v1/proctoring/streams/{s.body['stream_id']}", headers=other).status_code
        == 404
    )
    assert s.env.client.get(s.path, headers=s.auth).status_code == 200
    assert s.env.client.get(s.path + "/reviews", headers=s.auth).status_code == 405


def server_event(s, version=1, **changes):
    artifact = uuid4()
    return EventEnvelope(
        producer="whiteboard",
        event_type="whiteboard.board_changed.v1",
        aggregate_id=artifact,
        aggregate_version=version,
        correlation_id=uuid4(),
        payload={
            "candidate_id": s.subject,
            "session_id": s.session_id,
            "stage_id": s.stage_id,
            "artifact_id": artifact,
        },
        **changes,
    )


def process(s, e):
    with Session(s.env.app.state.engine) as session, session.begin():
        return process_environment_event(
            session, e, s.env.app.state.processing_access, s.env.app.state.stage_access
        )


def test_signed_server_history_preserves_delayed_versions_and_dedupes(env, signatures):
    s = env
    newer = server_event(s, 3)
    old = newer.model_copy(
        update={
            "event_id": uuid4(),
            "aggregate_version": 1,
            "occurred_at": datetime.now(UTC) - timedelta(minutes=1),
        }
    )
    consumer = ProctoringConsumer(
        s.env.app.state.engine, signatures["proctoring"], s.env.app.state.settings
    )
    consumer.processing = s.env.app.state.processing_access
    consumer.stages = s.env.app.state.stage_access
    for e in [newer, old, newer]:
        raw, head = signatures["whiteboard"].sign(e)
        checked = signatures["proctoring"].verify(raw, head, str(e.event_id))
        with Session(s.env.app.state.engine) as session, session.begin():
            consumer.handler(checked)(session, checked)
    assert [e["details"]["aggregate_version"] for e in state(s)["events"]] == [3, 1]
    assert process(s, newer.model_copy(update={"event_id": uuid4()})) is True
    assert state(s)["summary"]["timeline_version"] == 2
    assert "client_telemetry_missing" in state(s)["summary"]["flags"]
    with pytest.raises(InvalidEvent):
        consumer.handler(newer.model_copy(update={"producer": "media"}))
    with pytest.raises(HTTPException):
        process(s, newer.model_copy(update={"aggregate_id": uuid4(), "event_id": uuid4()}))


def test_privacy_erases_all_material_and_blocks_delayed_resurrection(env):
    s = env
    create(s)
    ingest(s, [event(s, 1)])
    decide(s)
    e = deletion(s.subject)
    with Session(s.env.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, e) is True
        assert process_deletion_request(session, e) is False
    assert ingest(s, [event(s, 2)]).status_code == 409
    process(s, server_event(s))
    with Session(s.env.app.state.engine) as session:
        for model in (
            ClientStream,
            ProctorEvent,
            IntegrityReview,
            IntegrityTrack,
            IdempotencyRecord,
        ):
            assert not list(session.scalars(select(model)))
        assert session.get(ProctorSubject, str(s.subject)).blocked
        assert [o.envelope["event_type"] for o in session.scalars(select(Outbox))] == [
            "proctoring.data_deleted.v1"
        ]
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.env.app.state.settings), "0001_transport")


def test_signed_evaluation_summary_is_fresh_bound_and_replay_protected(env, signatures, service):
    s = env
    create(s)
    ingest(s, [event(s, 1, "paste")])
    decide(s)
    s.env.app.state.proctor_signatures = signatures["proctoring"]
    eval = service("evaluation")
    access = IntegrityAccess(eval.app.state.settings)
    access._signatures = signatures["evaluation"]
    captured = []

    def send(endpoint, raw, signature, **kwargs):
        captured.append((raw, signature))
        reply = s.env.client.post(
            "/internal/v1/" + endpoint,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise ValueError(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    access._send = send
    assert access.fetch(s.subject, s.session_id, s.stage_id).status == "inconclusive"
    raw, sig = captured[0]
    assert (
        s.env.client.post(
            "/internal/v1/integrity-summary",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": sig},
        ).status_code
        == 401
    )
    body = IntegrityRequest(
        candidate_id=s.subject,
        session_id=s.session_id,
        stage_id=s.stage_id,
        requester="evaluation",
        nonce=uuid4(),
        issued_at=datetime.now(UTC) - timedelta(minutes=1),
    )
    assert (
        s.env.client.post(
            "/internal/v1/integrity-summary",
            content=canonical(body),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": sign(signatures["evaluation"], REQUEST, body),
            },
        ).status_code
        == 401
    )
    s.denied = True
    with pytest.raises(HTTPException) as failed:
        access.fetch(s.subject, s.session_id, s.stage_id)
    assert failed.value.status_code == 503


@pytest.mark.parametrize("format", ["code", "sql", "whiteboard", "voice", "vcv"])
def test_real_signed_assessment_admission_and_consent_revocation(
    service, token, signatures, format
):
    from test_assessment_sessions import make_session, plan
    from test_company_tasks import package

    from reverse_hr.domains.privacy import ConsentRecord
    from reverse_hr.processing_access import ProcessingAccess
    from reverse_hr.stage_access import StageAccess

    s = SimpleNamespace(env=service("proctoring"), subject=uuid4())
    assessment, privacy = service("assessment"), service("privacy")
    s.auth = token(s.subject)
    s.reviewer = token(roles=("assessment_reviewer",), amr=["mfa"])
    assessment.app.state.assessment_signatures = signatures["assessment"]
    privacy.app.state.privacy_signatures = signatures["privacy"]

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

    for target, name in [(s.env, "proctoring"), (assessment, "assessment")]:
        access = ProcessingAccess(target.app.state.settings)
        access._signatures = signatures[name]
        access._send = sender(privacy)
        target.app.state.processing_access = access
    stages = StageAccess(s.env.app.state.settings)
    stages._signatures = signatures["proctoring"]
    stages._send = sender(assessment)
    s.env.app.state.stage_access = stages
    consent = privacy.client.post(
        "/v1/consents",
        headers=headers(s.auth, "consent"),
        json={"purpose": "assessment", "document_version": "demo-v1"},
    ).json()["consent_id"]
    version, _, _ = plan(assessment, token, package(format))
    reply, _, _ = make_session(assessment, token, version, s.subject, consent=UUID(consent))
    assert reply.status_code == 201, reply.text
    s.session_id = UUID(reply.json()["session_id"])
    s.stage_id = UUID(reply.json()["stages"][0]["stage_id"])
    s.body = {
        "session_id": str(s.session_id),
        "stage_id": str(s.stage_id),
        "stream_id": str(uuid4()),
        "client_started_at": datetime.now(UTC).isoformat(),
    }
    s.path = f"/v1/proctoring/candidates/{s.subject}/sessions/{s.session_id}/stages/{s.stage_id}"
    assert (
        s.env.client.post(
            "/v1/proctoring/streams", headers=headers(s.auth, "premature"), json=s.body
        ).status_code
        == 409
    )
    path = f"/v1/assessment-sessions/{s.session_id}"
    assert (
        assessment.client.post(path + "/start", headers=headers(s.auth, "start", 1)).status_code
        == 200
    )
    assert (
        assessment.client.post(
            path + f"/stages/{s.stage_id}/start", headers=headers(s.auth, "stage", 2)
        ).status_code
        == 200
    )
    assert create(s)["timeline_version"] == 0
    assert ingest(s, [event(s, 1, "paste")]).status_code == 200
    # Exercise the real producer/outbox/verified consumer chain for every format.
    import hashlib
    from unittest.mock import Mock

    from reverse_hr.recording_access import RecordingAccess

    name = (
        "coding-workspace"
        if format in {"code", "sql"}
        else "whiteboard"
        if format == "whiteboard"
        else "media"
    )
    source = service(name)
    source_processing = ProcessingAccess(source.app.state.settings)
    source_processing._signatures = signatures[name]
    source_processing._send = sender(privacy)
    source.app.state.processing_access = source_processing
    source_stages = StageAccess(source.app.state.settings)
    source_stages._signatures = signatures[name]
    source_stages._send = sender(assessment)
    source.app.state.stage_access = source_stages
    artifact_body = {"session_id": str(s.session_id), "stage_id": str(s.stage_id)}
    if name == "coding-workspace":
        artifact_path = "/v1/workspaces"
        artifact_body["files"] = [
            {"path": "main.py" if format == "code" else "query.sql", "content": ""}
        ]
    elif name == "whiteboard":
        artifact_path = "/v1/boards"
    else:
        artifact_path = "/v1/recordings"
        recording = privacy.client.post(
            "/v1/consents",
            headers=headers(s.auth, "recording"),
            json={"purpose": "recording", "document_version": "demo-v1"},
        ).json()["consent_id"]
        recording_access = RecordingAccess(source.app.state.settings)
        recording_access._signatures = signatures[name]
        recording_access._send = sender(privacy)
        source.app.state.recording_access = recording_access
        raw = b"\x1aE\xdf\xa3synthetic"
        artifact_body |= {
            "recording_consent_id": recording,
            "mime": "audio/webm" if format == "voice" else "video/webm",
            "size": len(raw),
            "digest": hashlib.sha256(raw).hexdigest(),
            "client_duration_ms": 1000,
        }
    created = source.client.post(
        artifact_path, headers=headers(s.auth, "artifact"), json=artifact_body
    )
    assert created.status_code == 201, created.text
    with Session(source.app.state.engine) as session:
        generated = [
            EventEnvelope.model_validate(o.envelope)
            for o in session.scalars(select(Outbox))
            if o.envelope["event_type"].endswith("_observed.v1") or name != "coding-workspace"
        ]
    assert len(generated) == 1
    consumer = ProctoringConsumer(
        s.env.app.state.engine, signatures["proctoring"], s.env.app.state.settings
    )
    consumer.processing = s.env.app.state.processing_access
    consumer.stages = stages
    channel = Mock()
    raw, signed = signatures[name].sign(generated[0])
    props = SimpleNamespace(headers=signed, message_id=str(generated[0].event_id))
    method = SimpleNamespace(exchange=f"events.{name}", delivery_tag=1)
    consumer(channel, method, props, raw)
    assert channel.basic_ack.call_count == 1
    consumer(channel, method, props, raw)
    assert state(s)["summary"]["timeline_version"] == 2
    assert state(s)["events"][-1]["source"] == name
    assert decide(s, "inconclusive").status_code == 200
    # Competence storage lives elsewhere and remains untouched by the integrity decision.
    assert state(s)["summary"]["status"] == "inconclusive"
    with Session(privacy.app.state.engine) as session, session.begin():
        session.get(ConsentRecord, consent).status = "revoked"
    assert ingest(s, [event(s, 2)]).status_code == 409
    assert s.env.client.get(s.path, headers=s.reviewer).status_code == 409


def test_evaluation_bridge_returns_independent_summary_without_score_change(
    env, service, token, signatures
):
    from reverse_hr.domains.evaluation import EvaluationIntake

    s = env
    create(s)
    ingest(s, [event(s, 1, "paste")])
    decide(s, "concern", [state(s)["events"][0]["event_id"]])
    evaluation = service("evaluation")
    s.env.app.state.proctor_signatures = signatures["proctoring"]
    access = IntegrityAccess(evaluation.app.state.settings)
    access._signatures = signatures["evaluation"]

    def sender(endpoint, raw, signature, **kwargs):
        reply = s.env.client.post(
            "/internal/v1/" + endpoint,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise ValueError(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    access._send = sender
    evaluation.app.state.integrity_access = access
    with Session(evaluation.app.state.engine) as session, session.begin():
        session.add(
            EvaluationIntake(
                stage_id=str(s.stage_id),
                candidate_id=str(s.subject),
                session_id=str(s.session_id),
                workspace_id=str(uuid4()),
                snapshot_id=str(uuid4()),
                status="reviewed",
                score=92,
                version=4,
                received_at=datetime.now(UTC),
            )
        )
    path = f"/v1/evaluations/{s.stage_id}/integrity"
    assert evaluation.client.get(path, headers=s.reviewer).json()["status"] == "concern"
    assert (
        evaluation.client.get(
            path, headers=token(s.subject, roles=("assessment_reviewer",), amr=["mfa"])
        ).status_code
        == 403
    )
    assert evaluation.client.get(path, headers=token(roles=("employer",))).status_code == 403
    with Session(evaluation.app.state.engine) as session:
        row = session.get(EvaluationIntake, str(s.stage_id))
        assert (row.score, row.version, row.status) == (92, 4, "reviewed")


def test_event_cap_and_technical_outage_do_not_partially_store_batch(env, monkeypatch):
    import reverse_hr.domains.proctoring as domain

    s = env
    create(s)
    monkeypatch.setattr(domain, "MAX_EVENTS", 1)
    assert ingest(s, [event(s, 1), event(s, 2)]).status_code == 409
    assert state(s)["summary"]["timeline_version"] == 0

    def fail(*_):
        raise HTTPException(503)

    s.env.app.state.stage_access.check_stage = fail
    assert ingest(s, [event(s, 1)]).status_code == 503
    with Session(s.env.app.state.engine) as session:
        assert not list(session.scalars(select(ProctorEvent)))


def test_empty_migration_roundtrip_and_readiness(service):
    s = service("proctoring")
    settings = s.app.state.settings
    assert s.client.get("/health/ready").status_code == 200
    command.downgrade(migration_config(settings), "0001_transport")
    assert s.client.get("/health/ready").status_code == 503
    command.upgrade(migration_config(settings), "head")
    assert s.client.get("/health/ready").status_code == 200


def test_reviewer_deletion_removes_free_text_and_invalidates_decision(env):
    s = env
    create(s)
    ingest(s, [event(s, 1)])
    decide(s, "clear")
    reviewer = UUID(state(s)["summary"]["latest_review"]["reviewer_id"])
    with Session(s.env.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(reviewer))
    assert state(s, auth=s.auth)["summary"]["status"] == "needs_review"
    assert state(s, auth=s.auth)["summary"]["latest_review"] is None
    with Session(s.env.app.state.engine) as session:
        assert not list(session.scalars(select(IntegrityReview)))
        assert len(list(session.scalars(select(ProctorEvent)))) == 1


def test_timezones_normalized_to_utc_in_storage_and_timeline(env):
    from datetime import timezone

    s = env
    start = datetime.now(UTC).astimezone(timezone(timedelta(hours=5)))
    s.body["client_started_at"] = start.isoformat()
    create(s)
    assert ingest(s, [event(s, 1)]).status_code == 200
    result = state(s)
    assert result["summary"]["streams"][0]["client_started_at"].endswith("Z")
    assert abs(result["summary"]["streams"][0]["clock_or_delivery_offset_ms"]) < 30000
    assert result["events"][0]["client_time"].endswith("Z")
    assert result["events"][0]["received_at"].endswith("Z")
    assert "client_clock_discontinuity" not in result["summary"]["flags"]


def test_generated_broker_topology_keeps_runner_contract_and_routes_proctoring(tmp_path):
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    from reverse_hr.domains.proctoring import SERVER_KINDS

    root = Path(__file__).resolve().parents[1]
    (tmp_path / ".env").write_text("RABBITMQ_PASSWORD=synthetic-test-only\n")
    result = subprocess.run(
        [sys.executable, str(root / "scripts/configure_events.py")],
        cwd=tmp_path,
        env={
            "PATH": os.environ["PATH"],
            "PYTHONPATH": str(root / "src"),
            "PYTHONDONTWRITEBYTECODE": "1",
        },
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    definitions = json.loads((tmp_path / ".secrets/rabbitmq-definitions.json").read_text())
    bindings = definitions["bindings"]
    assert {
        b["routing_key"]
        for b in bindings
        if b["destination"] == "code-runner.incoming" and b["source"] == "events.coding-workspace"
    } == {"coding-workspace.run_requested.v1"}
    assert any(
        b["destination"] == "code-runner.incoming"
        and b["routing_key"] == "assessment.stage_submitted.v1"
        for b in bindings
    )
    proctor = {
        b["routing_key"]
        for b in bindings
        if b["destination"] == "proctoring.incoming" and b["source"].startswith("events.")
    }
    assert SERVER_KINDS | {"privacy.deletion_requested.v1"} == proctor
    assert any(
        b["destination"] == "privacy.incoming" and b["routing_key"] == "proctoring.data_deleted.v1"
        for b in bindings
    )
