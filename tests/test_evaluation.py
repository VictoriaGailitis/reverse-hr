from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_event_transport import signatures as signatures_fixture

from reverse_hr.db import Inbox, Outbox
from reverse_hr.domains.evaluation import (
    EvaluationIntake,
    EvaluationSubject,
    process_deletion_request,
    process_submission,
)
from reverse_hr.event_transport import EvaluationConsumer
from reverse_hr.events import EventEnvelope
from reverse_hr.migrate import migration_config

signatures = signatures_fixture


def delivery(signatures, event):
    body, headers = signatures[event.producer].sign(event)
    return (
        SimpleNamespace(exchange=f"events.{event.producer}", delivery_tag=1),
        SimpleNamespace(headers=headers, message_id=str(event.event_id)),
        body,
    )


def submission():
    stage = uuid4()
    return EventEnvelope(
        producer="assessment",
        event_type="assessment.stage_submitted.v1",
        correlation_id=uuid4(),
        aggregate_id=stage,
        aggregate_version=3,
        payload={
            "stage_id": stage,
            **{
                name: uuid4()
                for name in ("candidate_id", "session_id", "workspace_id", "snapshot_id")
            },
        },
    )


def apply(app, event, access=None):
    with Session(app.state.engine) as session, session.begin():
        return process_submission(session, event, access or app.state.processing_access)


def rows(app, model):
    with Session(app.state.engine) as session:
        return session.scalars(select(model)).all()


def test_private_intake_natural_and_inbox_duplicates(service, token):
    target = service("evaluation")
    event = submission()
    assert apply(target.app, event)
    assert not apply(target.app, event)
    assert apply(target.app, event.model_copy(update={"event_id": uuid4()}))
    assert len(rows(target.app, EvaluationIntake)) == len(rows(target.app, Outbox)) == 1
    path = f"/v1/evaluations/stages/{event.aggregate_id}"
    reply = target.client.get(path, headers=token(event.payload["candidate_id"]))
    assert reply.status_code == 200
    assert reply.json()["status"] == "awaiting_material"
    assert reply.json()["score"] is reply.json()["confirmed_grade"] is None
    assert reply.json()["demo"] is True
    assert "snapshot_id" not in reply.text and "workspace_id" not in reply.text
    assert target.client.get(path, headers=token()).status_code == 404
    assert target.client.get(path, headers=token(roles=("employer",))).status_code == 403
    assert target.client.get(path).status_code == 401
    assert target.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("field", ["candidate_id", "session_id", "workspace_id", "snapshot_id"])
def test_same_stage_conflicting_reference_rolls_back_inbox(service, field):
    target = service("evaluation")
    event = submission()
    apply(target.app, event)
    conflict = event.model_copy(
        update={"event_id": uuid4(), "payload": event.payload | {field: uuid4()}}
    )
    with pytest.raises(HTTPException) as exc:
        apply(target.app, conflict)
    assert exc.value.status_code == 409
    assert len(rows(target.app, Inbox)) == 1
    assert len(rows(target.app, Outbox)) == 1


@pytest.mark.parametrize(
    "change",
    [
        {"aggregate_version": 2},
        {"aggregate_id": uuid4()},
        {"producer": "hiring"},
        {"event_type": "assessment.stage_started.v1"},
        {"occurred_at": None},
    ],
)
def test_malformed_submission_no_effect(service, change):
    target = service("evaluation")
    if "occurred_at" in change:
        # Compute at execution, not collection: a full run may take > 5 minutes.
        change = change | {"occurred_at": datetime.now(UTC) + timedelta(minutes=5)}
    with pytest.raises(HTTPException):
        apply(target.app, submission().model_copy(update=change))
    assert not rows(target.app, Inbox)
    assert not rows(target.app, EvaluationIntake)


@pytest.mark.parametrize("code", [409, 503])
def test_privacy_deny_or_unavailable(service, code):
    target = service("evaluation")
    event = submission()
    access = SimpleNamespace(check=Mock(side_effect=HTTPException(code)))
    if code == 503:
        with pytest.raises(HTTPException):
            apply(target.app, event, access)
        assert not rows(target.app, Inbox)
        apply(target.app, event)
        assert len(rows(target.app, EvaluationIntake)) == 1
    else:
        apply(target.app, event, access)
        assert not rows(target.app, EvaluationIntake)
        assert len(rows(target.app, Inbox)) == 1


def test_outbox_failure_atomic_retry(service, monkeypatch):
    target = service("evaluation")
    event = submission()
    from reverse_hr.domains import evaluation

    original = evaluation.enqueue
    monkeypatch.setattr(evaluation, "enqueue", Mock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        apply(target.app, event)
    assert not rows(target.app, Inbox)
    assert not rows(target.app, EvaluationIntake)
    monkeypatch.setattr(evaluation, "enqueue", original)
    assert apply(target.app, event)


def test_deletion_purges_blocks_late_events_and_single_ack(service, token):
    target = service("evaluation")
    event = submission()
    apply(target.app, event)
    request = uuid4()
    deletion = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request,
        aggregate_version=1,
        payload={"candidate_id": event.payload["candidate_id"], "request_id": request},
    )
    for incoming in (deletion, deletion.model_copy(update={"event_id": uuid4()})):
        with Session(target.app.state.engine) as session, session.begin():
            process_deletion_request(session, incoming)
    access = SimpleNamespace(check=Mock(side_effect=AssertionError("No access after tombstone")))
    apply(target.app, event.model_copy(update={"event_id": uuid4()}), access)
    assert not rows(target.app, EvaluationIntake)
    assert rows(target.app, EvaluationSubject)[0].blocked
    assert [r.envelope["event_type"] for r in rows(target.app, Outbox)] == [
        "evaluation.data_deleted.v1"
    ]
    assert (
        target.client.get(
            f"/v1/evaluations/stages/{event.aggregate_id}",
            headers=token(event.payload["candidate_id"]),
        ).status_code
        == 409
    )
    with pytest.raises(RuntimeError, match="populated Evaluation"):
        command.downgrade(migration_config(target.app.state.settings), "0001_transport")
    assert target.client.get("/health/ready").status_code == 200


def test_authenticated_transport_commit_ack_and_tamper(service, signatures):
    target = service("evaluation")
    consumer = EvaluationConsumer(
        target.app.state.engine, signatures["evaluation"], target.app.state.settings
    )
    consumer.access = target.app.state.processing_access
    event = submission()
    channel = Mock()
    channel.basic_publish.return_value = True
    consumer(channel, *delivery(signatures, event))
    assert len(rows(target.app, EvaluationIntake)) == 1
    channel.basic_ack.assert_called_once()
    method, props, body = delivery(signatures, event)
    consumer(channel, method, props, body + b" ")
    assert len(rows(target.app, Inbox)) == 1
    assert channel.basic_publish.call_args.kwargs["exchange"] == "dead.evaluation"


def test_real_signed_privacy_restriction_before_local_deletion(service, token, signatures):
    from test_access import headers
    from test_processing_access import connect_access

    privacy, target = service("privacy"), service("evaluation")
    privacy.app.state.privacy_signatures = signatures["privacy"]
    target.app.state.processing_access = connect_access("evaluation", privacy, signatures)
    event = submission()
    apply(target.app, event)
    auth = token(event.payload["candidate_id"])
    path = f"/v1/evaluations/stages/{event.aggregate_id}"
    assert target.client.get(path, headers=auth).status_code == 200
    assert privacy.client.post("/v1/deletion-requests", headers=headers(auth)).status_code == 202
    assert target.client.get(path, headers=auth).status_code == 409
    late = submission()
    late = late.model_copy(
        update={"payload": late.payload | {"candidate_id": event.payload["candidate_id"]}}
    )
    apply(target.app, late)
    assert len(rows(target.app, EvaluationIntake)) == 1


def test_empty_downgrade_and_readiness(service):
    target = service("evaluation")
    command.downgrade(migration_config(target.app.state.settings), "0001_transport")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(migration_config(target.app.state.settings), "head")
    assert target.client.get("/health/ready").status_code == 200


def test_assessment_submission_outbox_to_signed_evaluation_intake(service, token, signatures):
    from test_assessment_lifecycle import setup as lifecycle_setup
    from test_assessment_lifecycle import start, submit

    lifecycle = lifecycle_setup.__wrapped__(service, token)
    start(lifecycle)
    response = submit(lifecycle)
    assert response.status_code == 200
    assessment = lifecycle[0][1]
    with Session(assessment.app.state.engine) as session:
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "assessment.stage_submitted.v1"
        )
    target = service("evaluation")
    consumer = EvaluationConsumer(
        target.app.state.engine, signatures["evaluation"], target.app.state.settings
    )
    consumer.access = target.app.state.processing_access
    channel = Mock()
    consumer(channel, *delivery(signatures, event))
    consumer(channel, *delivery(signatures, event))
    assert channel.basic_ack.call_count == 2
    channel.basic_publish.assert_not_called()
    intake = rows(target.app, EvaluationIntake)[0]
    assert intake.snapshot_id == response.json()["progress"][0]["snapshot_id"]
    assert intake.status == "awaiting_material"
    reply = target.client.get(
        f"/v1/evaluations/stages/{event.aggregate_id}", headers=lifecycle[0][2]
    )
    assert reply.status_code == 200 and reply.json()["score"] is None


def test_transport_unavailable_retries_without_partial_intake(service, signatures):
    target = service("evaluation")
    consumer = EvaluationConsumer(
        target.app.state.engine, signatures["evaluation"], target.app.state.settings
    )
    consumer.access = SimpleNamespace(check=Mock(side_effect=HTTPException(503)))
    channel = Mock()
    channel.basic_publish.return_value = True
    event = submission()
    consumer(channel, *delivery(signatures, event))
    assert not rows(target.app, Inbox)
    assert not rows(target.app, EvaluationIntake)
    assert channel.basic_publish.call_args.kwargs["exchange"] == "retry.evaluation"
    channel.basic_ack.assert_called_once()


def test_deletion_ack_failure_preserves_intake_and_allows_retry(service, monkeypatch):
    from reverse_hr.domains import evaluation

    target = service("evaluation")
    event = submission()
    apply(target.app, event)
    request_id = uuid4()
    deletion = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": event.payload["candidate_id"], "request_id": request_id},
    )
    original = evaluation.enqueue
    monkeypatch.setattr(evaluation, "enqueue", Mock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        with Session(target.app.state.engine) as session, session.begin():
            process_deletion_request(session, deletion)
    assert len(rows(target.app, EvaluationIntake)) == 1
    assert not rows(target.app, EvaluationSubject)[0].blocked
    assert len(rows(target.app, Inbox)) == 1
    assert rows(target.app, Outbox)[0].envelope["event_type"] == "evaluation.intake_created.v1"
    monkeypatch.setattr(evaluation, "enqueue", original)
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion)
    assert not rows(target.app, EvaluationIntake)
