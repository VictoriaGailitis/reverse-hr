import base64
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reverse_hr.auth import Principal
from reverse_hr.db import Base, IdempotencyRecord, Outbox, enqueue, make_engine
from reverse_hr.domains.privacy import ConsentRecord, ContactGrant, PrivacyBase
from reverse_hr.event_transport import InvalidEvent, PrivacyConsumer, Signatures, publish_one
from reverse_hr.events import EventEnvelope
from reverse_hr.replay import replay_outbox
from reverse_hr.settings import SERVICES, SIGNING_SERVICES, Settings


@pytest.fixture
def signatures():
    keys = {name: Ed25519PrivateKey.generate() for name in SIGNING_SERVICES}
    public = {
        name: base64.b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode()
        for name, key in keys.items()
    }
    return {
        name: Signatures(
            name,
            key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            ),
            public,
        )
        for name, key in keys.items()
    }


@pytest.fixture
def engine(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path}/transport.db")
    Base.metadata.create_all(engine)
    PrivacyBase.metadata.create_all(engine)
    yield engine
    engine.dispose()


def accepted_event(engine):
    candidate, consent, invitation = uuid4(), uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            ConsentRecord(
                consent_id=str(consent),
                candidate_id=str(candidate),
                purpose="contact_disclosure",
                document_version="demo-v1",
                status="active",
                version=1,
                granted_at=datetime.now(UTC),
            )
        )
    return EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=invitation,
        aggregate_version=1,
        payload={
            "candidate_id": candidate,
            "invitation_id": invitation,
            "organization_id": uuid4(),
            "consent_id": consent,
        },
    )


def delivery(signatures, event, exchange="events.hiring", headers=None):
    body, signed = signatures["hiring"].sign(event)
    return (
        SimpleNamespace(exchange=exchange, delivery_tag=1),
        SimpleNamespace(headers=signed | (headers or {}), message_id=str(event.event_id)),
        body,
    )


def test_signature_covers_body_identity_and_event_id(engine, signatures):
    event = accepted_event(engine)
    body, headers = signatures["hiring"].sign(event)
    assert signatures["privacy"].verify(body, headers, str(event.event_id)) == event
    for forged_body, forged_headers, message_id in (
        (body + b" ", headers, str(event.event_id)),
        (body, headers | {"hr-producer": "candidate"}, str(event.event_id)),
        (body, headers | {"hr-signature": "wrong"}, str(event.event_id)),
        (body, headers, str(uuid4())),
        (body, {}, str(event.event_id)),
        (b"x" * 65537, headers, str(event.event_id)),
    ):
        with pytest.raises(InvalidEvent):
            signatures["privacy"].verify(forged_body, forged_headers, message_id)
    with pytest.raises(InvalidEvent):
        signatures["candidate"].sign(event)


def test_outbox_waits_for_confirmation_retries_and_stops(engine, signatures):
    event = accepted_event(engine)
    now = datetime.now(UTC)
    settings = Settings(service_name="hiring", event_max_attempts=2)
    with Session(engine) as session, session.begin():
        enqueue(session, event)
    channel = Mock()
    channel.basic_publish.side_effect = RuntimeError("not confirmed")
    assert publish_one(
        engine, channel, signatures["hiring"], settings, now=now + timedelta(seconds=1)
    )
    with Session(engine) as session:
        assert session.get(Outbox, str(event.event_id)).status == "pending"
        assert session.get(Outbox, str(event.event_id)).published_at is None
    assert not publish_one(engine, channel, signatures["hiring"], settings, now=now)
    assert publish_one(
        engine, channel, signatures["hiring"], settings, now=now + timedelta(seconds=10)
    )
    with Session(engine) as session:
        assert session.get(Outbox, str(event.event_id)).status == "dead"
        assert session.get(Outbox, str(event.event_id)).attempts == 2


def test_outbox_confirmed_and_foreign_producer_rejected(engine, signatures):
    event = accepted_event(engine)
    with Session(engine) as session, session.begin():
        enqueue(session, event)
    channel = Mock()
    settings = Settings(service_name="hiring")
    assert publish_one(engine, channel, signatures["hiring"], settings)
    assert channel.basic_publish.call_args.kwargs["mandatory"] is True
    assert channel.basic_publish.call_args.kwargs["properties"].delivery_mode == 2
    with Session(engine) as session:
        assert session.get(Outbox, str(event.event_id)).status == "published"
    second = event.model_copy(update={"event_id": uuid4()})
    with Session(engine) as session, session.begin():
        enqueue(session, second)
    channel.reset_mock()
    assert publish_one(engine, channel, signatures["candidate"], Settings(service_name="candidate"))
    channel.basic_publish.assert_not_called()
    with Session(engine) as session:
        assert session.get(Outbox, str(second.event_id)).status == "dead"


def test_consumer_commits_before_ack_and_deduplicates(engine, signatures):
    event = accepted_event(engine)
    consumer = PrivacyConsumer(engine, signatures["privacy"], Settings(service_name="privacy"))
    channel = Mock()

    def acknowledged(**kwargs):
        with Session(engine) as session:
            assert len(list(session.scalars(select(ContactGrant)))) == 1

    channel.basic_ack.side_effect = acknowledged
    consumer(channel, *delivery(signatures, event))
    consumer(channel, *delivery(signatures, event))
    assert channel.basic_ack.call_count == 2
    channel.basic_publish.assert_not_called()


def test_forgery_goes_to_redacted_dlq_and_not_to_business(engine, signatures):
    event = accepted_event(engine)
    consumer = PrivacyConsumer(engine, signatures["privacy"], Settings(service_name="privacy"))
    method, properties, body = delivery(signatures, event)
    channel = Mock()
    consumer(channel, method, properties, body + b"private@example.test")
    publication = channel.basic_publish.call_args.kwargs
    assert publication["exchange"] == "dead.privacy"
    assert publication["body"] == b'{"code":"invalid_event"}'
    with Session(engine) as session:
        assert session.scalar(select(ContactGrant)) is None
    channel.basic_ack.assert_called_once()


@pytest.mark.parametrize(
    "failure", [OperationalError("synthetic", {}, Exception()), HTTPException(503)]
)
def test_transient_failure_uses_delayed_retry_then_dlq(engine, signatures, monkeypatch, failure):
    event = accepted_event(engine)
    consumer = PrivacyConsumer(
        engine, signatures["privacy"], Settings(service_name="privacy", event_max_attempts=2)
    )
    channel = Mock()

    def fail(*args, **kwargs):
        raise failure

    monkeypatch.setattr("reverse_hr.event_transport.process_accepted_invitation", fail)
    consumer(channel, *delivery(signatures, event))
    assert channel.basic_publish.call_args.kwargs["exchange"] == "retry.privacy"
    assert channel.basic_publish.call_args.kwargs["properties"].headers["hr-attempt"] == 1
    consumer(channel, *delivery(signatures, event, "incoming.privacy", {"hr-attempt": 1}))
    assert channel.basic_publish.call_args.kwargs["exchange"] == "dead.privacy"


def test_failed_retry_publication_does_not_ack_original(engine, signatures, monkeypatch):
    event = accepted_event(engine)
    consumer = PrivacyConsumer(engine, signatures["privacy"], Settings(service_name="privacy"))
    channel = Mock()
    channel.basic_publish.side_effect = RuntimeError("broker unavailable")

    def fail(*args, **kwargs):
        raise OperationalError("synthetic failure", {}, Exception())

    monkeypatch.setattr("reverse_hr.event_transport.process_accepted_invitation", fail)
    with pytest.raises(RuntimeError):
        consumer(channel, *delivery(signatures, event))
    channel.basic_ack.assert_not_called()


def test_administrative_replay_requires_mfa_and_records_reason(engine, signatures):
    event = accepted_event(engine)
    with Session(engine) as session, session.begin():
        enqueue(session, event)
        session.flush()
        row = session.get(Outbox, str(event.event_id))
        row.status, row.attempts = "dead", 5
    for principal in (
        Principal(uuid4(), frozenset({"candidate"}), True),
        Principal(uuid4(), frozenset({"technical_admin"}), False),
    ):
        with pytest.raises(HTTPException) as caught:
            replay_outbox(
                engine, principal, event.event_id, uuid4(), "Synthetic repair", signatures["hiring"]
            )
        assert caught.value.status_code == 403
    admin, key = Principal(uuid4(), frozenset({"technical_admin"}), True), uuid4()
    response = replay_outbox(
        engine, admin, event.event_id, key, "Synthetic repair", signatures["hiring"]
    )
    assert response.status_code == 200
    with Session(engine) as session, session.begin():
        row = session.get(Outbox, str(event.event_id))
        assert row.status == "pending"
        assert row.attempts == 0
        row.attempts = 1
        audit = session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.operation == "admin:outbox_replay")
        )
        assert audit.actor_id == str(admin.subject)
        assert "Synthetic repair" in audit.response
    assert (
        replay_outbox(
            engine, admin, event.event_id, key, "Synthetic repair", signatures["hiring"]
        ).body
        == response.body
    )
    with Session(engine) as session:
        assert session.get(Outbox, str(event.event_id)).attempts == 1
    with pytest.raises(HTTPException) as caught:
        replay_outbox(engine, admin, event.event_id, uuid4(), "Repair again", signatures["hiring"])
    assert caught.value.status_code == 409


def test_signed_deletion_ack_requires_own_producer_exchange(engine, signatures):
    from reverse_hr.domains.privacy import DeletionRequest, DeletionTarget, PrivacySubject

    subject, request_id = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add(PrivacySubject(candidate_id=str(subject), blocked=True))
        session.add(
            DeletionRequest(
                request_id=str(request_id),
                candidate_id=str(subject),
                requested_at=datetime.now(UTC),
            )
        )
        session.add(
            DeletionTarget(request_id=str(request_id), service="candidate", status="pending")
        )
    event = EventEnvelope(
        event_type="candidate.data_deleted.v1",
        producer="candidate",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    body, signed = signatures["candidate"].sign(event)
    properties = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    consumer = PrivacyConsumer(engine, signatures["privacy"], Settings(service_name="privacy"))
    wrong = Mock()
    consumer(wrong, SimpleNamespace(exchange="events.hiring", delivery_tag=1), properties, body)
    assert wrong.basic_publish.call_args.kwargs["exchange"] == "dead.privacy"
    with Session(engine) as session:
        assert session.get(DeletionTarget, (str(request_id), "candidate")).status == "pending"
    channel = Mock()
    consumer(
        channel, SimpleNamespace(exchange="events.candidate", delivery_tag=2), properties, body
    )
    channel.basic_ack.assert_called_once_with(delivery_tag=2)
    channel.basic_publish.assert_not_called()
    with Session(engine) as session:
        assert session.get(DeletionTarget, (str(request_id), "candidate")).status == "deleted"


def test_candidate_consumer_commits_cleanup_before_ack_and_rejects_forgery(engine, signatures):
    from reverse_hr.domains.candidate import CandidateBase, CandidateProfile, CandidateSubject
    from reverse_hr.event_transport import CandidateConsumer

    CandidateBase.metadata.create_all(engine)
    subject, request_id = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add(
            CandidateProfile(
                candidate_id=str(subject),
                display_name="Synthetic",
                specialization="backend",
                declared_grade="junior",
                version=1,
            )
        )
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    body, signed = signatures["privacy"].sign(event)
    consumer = CandidateConsumer(
        engine, signatures["candidate"], Settings(service_name="candidate")
    )
    channel = Mock()
    props = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    consumer(channel, SimpleNamespace(exchange="events.hiring", delivery_tag=1), props, body)
    assert channel.basic_publish.call_args.kwargs["exchange"] == "dead.candidate"
    with Session(engine) as session:
        assert session.get(CandidateProfile, str(subject)) is not None
    channel.reset_mock()

    def ack(**kwargs):
        with Session(engine) as session:
            assert session.get(CandidateProfile, str(subject)) is None
            assert session.get(CandidateSubject, str(subject)).blocked
            assert (
                session.scalar(select(Outbox)).envelope["event_type"] == "candidate.data_deleted.v1"
            )

    channel.basic_ack.side_effect = ack
    consumer(channel, SimpleNamespace(exchange="events.privacy", delivery_tag=2), props, body)
    channel.basic_ack.assert_called_once_with(delivery_tag=2)
    channel.basic_publish.assert_not_called()


def test_employer_consumer_only_accepts_signed_privacy_request(engine, signatures):
    from reverse_hr.domains.employer import EmployerBase, EmployerSubject
    from reverse_hr.event_transport import EmployerConsumer

    EmployerBase.metadata.create_all(engine)
    subject, request_id = uuid4(), uuid4()
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    body, signed = signatures["privacy"].sign(event)
    consumer = EmployerConsumer(engine, signatures["employer"], Settings(service_name="employer"))
    props = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    channel = Mock()
    consumer(channel, SimpleNamespace(exchange="events.candidate", delivery_tag=1), props, body)
    assert channel.basic_publish.call_args.kwargs["exchange"] == "dead.employer"
    with Session(engine) as session:
        assert session.get(EmployerSubject, str(subject)) is None
    channel.reset_mock()

    def ack(**kwargs):
        with Session(engine) as session:
            assert session.get(EmployerSubject, str(subject)).blocked
            assert (
                session.scalar(select(Outbox)).envelope["event_type"] == "employer.data_deleted.v1"
            )

    channel.basic_ack.side_effect = ack
    consumer(channel, SimpleNamespace(exchange="events.privacy", delivery_tag=2), props, body)
    channel.basic_ack.assert_called_once_with(delivery_tag=2)


def test_final_signed_ack_commits_privacy_cleanup_before_broker_ack(engine, signatures):
    from reverse_hr.domains.privacy import DeletionRequest, DeletionTarget, PrivacySubject

    subject, request_id = uuid4(), uuid4()
    with Session(engine) as session, session.begin():
        session.add(PrivacySubject(candidate_id=str(subject), blocked=True))
        session.add(
            DeletionRequest(
                request_id=str(request_id),
                candidate_id=str(subject),
                requested_at=datetime.now(UTC),
            )
        )
        session.add(
            ConsentRecord(
                consent_id=str(uuid4()),
                candidate_id=str(subject),
                purpose="assessment",
                document_version="demo-v1",
                status="revoked",
                version=2,
                granted_at=datetime.now(UTC),
            )
        )
        for name in SERVICES:
            session.add(
                DeletionTarget(
                    request_id=str(request_id),
                    service=name,
                    status="pending"
                    if name == "audit"
                    else "restricted"
                    if name == "privacy"
                    else "deleted",
                )
            )
    event = EventEnvelope(
        event_type="audit.data_deleted.v1",
        producer="audit",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    body, headers = signatures["audit"].sign(event)
    props = SimpleNamespace(headers=headers, message_id=str(event.event_id))
    channel = Mock()

    def ack(**kwargs):
        with Session(engine) as session:
            assert session.get(DeletionRequest, str(request_id)).completed_at is not None
            assert session.scalar(select(ConsentRecord)) is None
            assert session.get(PrivacySubject, str(subject)).blocked

    channel.basic_ack.side_effect = ack
    consumer = PrivacyConsumer(engine, signatures["privacy"], Settings(service_name="privacy"))
    consumer(channel, SimpleNamespace(exchange="events.audit", delivery_tag=1), props, body)
    channel.basic_ack.assert_called_once_with(delivery_tag=1)
    channel.basic_publish.assert_not_called()


def test_assessment_signed_deletion_ack_follows_committed_cleanup(service, token, signatures):
    from test_assessment_sessions import deletion, make_session, plan

    from reverse_hr.domains.assessment_sessions import AssessmentSubject, PracticalSession
    from reverse_hr.event_transport import AssessmentConsumer

    assessment = service("assessment")
    version, _, _ = plan(assessment, token)
    subject = uuid4()
    created, _, _ = make_session(assessment, token, version, subject)
    assert created.status_code == 201
    event = deletion(subject)
    body, signed = signatures["privacy"].sign(event)
    props = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    engine = assessment.app.state.engine
    channel = Mock()

    def ack(**kwargs):
        with Session(engine) as session:
            assert session.get(PracticalSession, created.json()["session_id"]) is None
            assert session.get(AssessmentSubject, str(subject)).blocked
            acks = [
                row
                for row in session.scalars(select(Outbox))
                if row.envelope["aggregate_id"] == str(event.aggregate_id)
            ]
            assert len(acks) == 1
            assert acks[0].envelope["event_type"] == "assessment.data_deleted.v1"

    channel.basic_ack.side_effect = ack
    consumer = AssessmentConsumer(
        engine, signatures["assessment"], Settings(service_name="assessment")
    )
    consumer(channel, SimpleNamespace(exchange="events.privacy", delivery_tag=1), props, body)
    channel.basic_ack.assert_called_once_with(delivery_tag=1)
    channel.basic_publish.assert_not_called()
