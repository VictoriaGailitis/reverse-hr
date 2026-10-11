"""Signed Assessment export and local Candidate projection; no live infrastructure."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.core import Grade
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.confirmed_grade_access import (
    RESPONSE,
    ConfirmedGradeAccess,
    DecisionReceipt,
    DecisionRequest,
    DecisionSummary,
)
from reverse_hr.services.candidate.domain.candidate import process_deletion_request
from reverse_hr.services.candidate.domain.candidate_grades import (
    CandidateDecision,
    process_grade_decision,
)
from reverse_hr.shared.db import Outbox
from reverse_hr.shared.signing import canonical, sign
from tests.services.assessment.test_assessment_grades import decide, proposal, review
from tests.services.assessment.test_assessment_grades import setup as grade_setup
from tests.services.code_runner.test_code_runner import deletion
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture
setup = grade_setup


def event(candidate, *, decision=None, session=None):
    sid = session or uuid4()
    return EventEnvelope(
        producer="assessment",
        event_type="assessment.grade_decision_recorded.v1",
        correlation_id=uuid4(),
        aggregate_id=sid,
        aggregate_version=5,
        payload=dict(
            candidate_id=candidate,
            session_id=sid,
            decision_id=decision or uuid4(),
            reviewer_id=uuid4(),
        ),
    )


def apply(target, message, summary):
    access = SimpleNamespace(fetch=lambda **_: summary, check=lambda *_: None)
    with Session(target.app.state.engine) as session, session.begin():
        return process_grade_decision(session, message, access)


def test_signed_human_decision_reaches_candidate(setup, service, token, signatures):
    s = setup
    review(s)
    result = proposal(s)
    assert decide(s, evidence=result["evidence_digest"]).status_code == 200
    with Session(s.assessment.app.state.engine) as session:
        records = session.scalars(select(Outbox)).all()
        message = next(
            EventEnvelope.model_validate(r.envelope)
            for r in records
            if r.envelope["event_type"] == "assessment.grade_decision_recorded.v1"
        )
    target = service("candidate")
    candidate = message.payload["candidate_id"]
    auth = token(candidate)
    assert (
        target.client.post(
            "/v1/candidates/me",
            json=dict(display_name="Candidate", specialization="backend", declared_grade="lead"),
            headers=headers(auth, "profile"),
        ).status_code
        == 201
    )
    access = ConfirmedGradeAccess(target.app.state.settings)
    access._signatures = signatures["candidate"]

    def send(route, raw, signature, **_):
        response = s.assessment.client.post(
            "/internal/v1/" + route,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        assert response.status_code == 200, response.text
        return response.content, response.headers["X-HR-Signature"]

    access._send = send
    access.check = lambda *_: None
    with Session(target.app.state.engine) as session, session.begin():
        assert process_grade_decision(session, message, access)
    history = target.client.get("/v1/candidates/me/grade-history", headers=auth)
    assert history.status_code == 200
    assert history.json()[0]["target_grade"] == "junior"
    specialization = history.json()[0]["specialization"]
    profile = target.client.get("/v1/candidates/me", headers=auth).json()
    reply = target.client.put(
        "/v1/candidates/me",
        json=dict(display_name="Candidate", specialization=specialization, declared_grade="lead"),
        headers=headers(auth, "specialization", profile["version"]),
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["confirmed_grade"] == "junior"
    assert reply.json()["declared_grade"] == "lead"


def test_late_events_duplicates_specializations_and_erasure(service, token):
    target = service("candidate")
    candidate = uuid4()
    auth = token(candidate)
    target.client.post(
        "/v1/candidates/me",
        json=dict(display_name="C", specialization="backend", declared_grade="junior"),
        headers=headers(auth, "create"),
    )
    first = event(candidate)
    summary = DecisionSummary(
        specialization="backend",
        target_grade="senior",
        status="confirmed",
        decided_at=datetime.now(UTC),
    )
    assert apply(target, first, summary)
    assert not apply(target, first, summary)
    repeated = first.model_copy(update={"event_id": uuid4()})
    assert apply(target, repeated, summary)
    assert target.client.get("/v1/candidates/me", headers=auth).json()["version"] == 2
    apply(
        target,
        event(candidate),
        summary.model_copy(
            update={
                "target_grade": Grade.junior,
                "decided_at": datetime.now(UTC) - timedelta(days=2),
            }
        ),
    )
    apply(
        target,
        event(candidate),
        summary.model_copy(update={"specialization": "frontend", "target_grade": Grade.lead}),
    )
    apply(
        target,
        event(candidate),
        summary.model_copy(update={"status": "rejected", "target_grade": Grade.lead}),
    )
    profile = target.client.get("/v1/candidates/me", headers=auth).json()
    assert profile["confirmed_grade"] == "senior" and profile["version"] == 2
    assert len(target.client.get("/v1/candidates/me/grade-history", headers=auth).json()) == 4
    assert target.client.get("/v1/candidates/me/grade-history", headers=token(uuid4())).json() == []
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(candidate))
    with pytest.raises(HTTPException) as exc:
        apply(target, event(candidate), summary)
    assert exc.value.status_code == 409
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(CandidateDecision)) is None


def test_collision_rolls_back_and_migration_preserves_history(service):
    target = service("candidate")
    candidate = uuid4()
    message = event(candidate)
    summary = DecisionSummary(
        specialization="backend",
        target_grade="middle",
        status="confirmed",
        decided_at=datetime.now(UTC),
    )
    apply(target, message, summary)
    with pytest.raises(HTTPException):
        apply(
            target,
            message.model_copy(update={"event_id": uuid4()}),
            summary.model_copy(update={"status": "rejected"}),
        )
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(target.app.state.settings), "0003_candidate")
    assert target.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize(
    "mutation", ["nonce", "session_id", "signature", "oversized", "stale", "denied"]
)
def test_decision_access_rejects_unbound_or_denied_response(service, signatures, mutation):
    target = service("candidate")
    access = ConfirmedGradeAccess(target.app.state.settings)
    access._signatures = signatures["candidate"]
    refs = event(uuid4()).payload | {"session_version": 5}

    def send(route, raw, signature, **_):
        request = DecisionRequest.model_validate_json(raw)
        receipt = DecisionReceipt(
            **request.model_dump(),
            allowed=True,
            decision=DecisionSummary(
                specialization="backend",
                target_grade="junior",
                status="confirmed",
                decided_at=datetime.now(UTC),
            ),
        )
        if mutation in {"nonce", "session_id"}:
            receipt = receipt.model_copy(update={mutation: uuid4()})
        if mutation == "stale":
            receipt = receipt.model_copy(
                update={"issued_at": datetime.now(UTC) - timedelta(minutes=1)}
            )
        if mutation == "denied":
            receipt = receipt.model_copy(update={"allowed": False, "decision": None})
        signature = sign(signatures["assessment"], RESPONSE, receipt)
        if mutation == "signature":
            signature = sign(signatures["candidate"], RESPONSE, receipt)
        return (b"x" * 4097 if mutation == "oversized" else canonical(receipt)), signature

    access._send = send
    with pytest.raises(HTTPException) as exc:
        access.fetch(**refs)
    assert exc.value.status_code == (409 if mutation == "denied" else 503)


def test_export_signature_nonce_binding_and_current_permission(setup, signatures):
    from reverse_hr.protocols.confirmed_grade_access import REQUEST
    from reverse_hr.shared.signing import verify

    s = setup
    assert decide(s, action="technical_failure").status_code == 200
    with Session(s.assessment.app.state.engine) as session:
        message = next(
            EventEnvelope.model_validate(r.envelope)
            for r in session.scalars(select(Outbox))
            if r.envelope["event_type"] == "assessment.grade_decision_recorded.v1"
        )
    body = DecisionRequest(
        **message.payload,
        session_version=message.aggregate_version,
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )

    def post(body, signer="candidate"):
        return s.assessment.client.post(
            "/internal/v1/confirmed-grade",
            json=body.model_dump(mode="json"),
            headers={"X-HR-Signature": sign(signatures[signer], REQUEST, body)},
        )

    assert post(body, "evaluation").status_code == 401
    response = post(body)
    assert response.status_code == 200, response.text
    receipt = DecisionReceipt.model_validate_json(response.content)
    verify(
        signatures["candidate"], "assessment", response.headers["X-HR-Signature"], RESPONSE, receipt
    )
    assert receipt.decision.status == "technical_failure"
    assert post(body).status_code == 401
    wrong = body.model_copy(update={"nonce": uuid4(), "reviewer_id": uuid4()})
    assert post(wrong).json()["allowed"] is False
    stale = body.model_copy(
        update={"nonce": uuid4(), "issued_at": datetime.now(UTC) - timedelta(minutes=1)}
    )
    assert post(stale).status_code == 401

    def deny(*_):
        raise HTTPException(409)

    s.assessment.app.state.processing_access.check_assessment = deny
    assert post(body.model_copy(update={"nonce": uuid4()})).json()["allowed"] is False


def test_empty_candidate_grade_migration_roundtrip(service):
    target = service("candidate")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200


def test_consumer_authentication_retry_and_commit_before_ack(service, signatures):
    from unittest.mock import Mock

    from reverse_hr.services.candidate.consumer import CandidateConsumer

    target = service("candidate")
    message = event(uuid4())
    summary = DecisionSummary(
        specialization="backend",
        target_grade="junior",
        status="confirmed",
        decided_at=datetime.now(UTC),
    )
    consumer = CandidateConsumer(
        target.app.state.engine, signatures["candidate"], target.app.state.settings
    )
    channel = Mock()
    raw, signed = signatures["assessment"].sign(message)
    method = SimpleNamespace(exchange="events.assessment", delivery_tag=1)
    properties = SimpleNamespace(headers=signed, message_id=str(message.event_id))

    def ack(**_):
        with Session(target.app.state.engine) as session:
            assert session.get(CandidateDecision, str(message.payload["decision_id"])) is not None

    consumer.access = SimpleNamespace(fetch=lambda **_: summary, check=lambda *_: None)
    channel.basic_ack.side_effect = ack
    consumer(channel, method, properties, raw)
    channel.basic_publish.assert_not_called()
    consumer(channel, method, properties, raw)
    assert channel.basic_ack.call_count == 2
    channel.reset_mock()
    channel.basic_ack.side_effect = None
    consumer(channel, method, properties, raw + b" ")
    assert channel.basic_publish.call_args.kwargs["body"] == b'{"code":"invalid_event"}'
    channel.reset_mock()

    def unavailable(**_):
        raise HTTPException(503)

    consumer.access.fetch = unavailable
    another = message.model_copy(update={"event_id": uuid4()})
    raw, signed = signatures["assessment"].sign(another)
    consumer(
        channel, method, SimpleNamespace(headers=signed, message_id=str(another.event_id)), raw
    )
    assert channel.basic_publish.call_args.kwargs["exchange"] == "retry.candidate"
