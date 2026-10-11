"""Real broker tests; requires disposable local broker and service-specific credentials."""

import os
import time
from datetime import UTC, datetime
from uuid import uuid4

import pika
import pytest
from alembic import command
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.migrate import migration_config
from reverse_hr.platform.settings import Settings
from reverse_hr.services.privacy.consumer import PrivacyConsumer
from reverse_hr.services.privacy.domain.privacy import ConsentRecord, ContactGrant
from reverse_hr.shared.db import enqueue, make_engine
from reverse_hr.shared.event_transport import Signatures, connect, publish_one

pytestmark = pytest.mark.skipif(
    not os.getenv("HR_TEST_HIRING_AMQP_URL"), reason="Broker not configured"
)


def settings(service):
    prefix = service.upper()
    return Settings(
        service_name=service,
        amqp_url=os.environ[f"HR_TEST_{prefix}_AMQP_URL"],
        database_url=os.environ[f"HR_TEST_{prefix}_DATABASE_URL"],
    )


def receive(channel, event_id, callback, timeout=10, queue="privacy.incoming"):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        method, properties, body = channel.basic_get(queue, auto_ack=False)
        if method:
            callback(channel, method, properties, body)
            if properties.message_id == str(event_id):
                return
        else:
            time.sleep(0.1)
    raise AssertionError("Expected event was not delivered")


def test_real_signed_outbox_to_privacy_and_repeat():
    hiring, privacy = settings("hiring"), settings("privacy")
    for config in (hiring, privacy):
        command.upgrade(migration_config(config), "head")
    producer_engine, consumer_engine = (
        make_engine(config.database_url.get_secret_value()) for config in (hiring, privacy)
    )
    producer_connection, publisher = connect(hiring)
    consumer_connection, subscriber = connect(privacy)
    signing, verifying = Signatures.from_settings(hiring), Signatures.from_settings(privacy)
    consumer = PrivacyConsumer(consumer_engine, verifying, privacy)
    candidate, invitation, consent = uuid4(), uuid4(), uuid4()
    event = EventEnvelope(
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
    try:
        with Session(consumer_engine) as session, session.begin():
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
        with Session(producer_engine) as session, session.begin():
            enqueue(session, event)
        assert publish_one(producer_engine, publisher, signing, hiring)
        receive(subscriber, event.event_id, consumer)
        body, headers = signing.sign(event)
        publisher.basic_publish(
            exchange="events.hiring",
            routing_key=event.event_type,
            body=body,
            mandatory=True,
            properties=pika.BasicProperties(
                delivery_mode=2, message_id=str(event.event_id), headers=headers
            ),
        )
        receive(subscriber, event.event_id, consumer)
        with Session(consumer_engine) as session:
            grants = list(
                session.scalars(
                    select(ContactGrant).where(ContactGrant.invitation_id == str(invitation))
                )
            )
            assert len(grants) == 1
            assert grants[0].status == "active"
    finally:
        producer_connection.close()
        consumer_connection.close()
        producer_engine.dispose()
        consumer_engine.dispose()


def test_broker_rejects_foreign_exchange_and_queue():
    connection, channel = connect(settings("candidate"))
    try:
        with pytest.raises(pika.exceptions.ChannelClosedByBroker) as caught:
            channel.basic_publish(
                exchange="events.hiring",
                routing_key="hiring.invitation_accepted.v1",
                body=b"{}",
                mandatory=True,
            )
        assert caught.value.reply_code == 403
    finally:
        connection.close()

    connection, channel = connect(settings("candidate"))
    try:
        with pytest.raises(pika.exceptions.ChannelClosedByBroker) as caught:
            channel.basic_get("privacy.incoming", auto_ack=False)
        assert caught.value.reply_code == 403
    finally:
        connection.close()


def test_real_retry_returns_after_ttl_and_preserves_signature(monkeypatch):
    hiring, privacy = settings("hiring"), settings("privacy")
    engine = make_engine(privacy.database_url.get_secret_value())
    producer_connection, publisher = connect(hiring)
    consumer_connection, subscriber = connect(privacy)
    consumer = PrivacyConsumer(engine, Signatures.from_settings(privacy), privacy)
    consent, candidate, invitation = uuid4(), uuid4(), uuid4()
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
    event = EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=invitation,
        aggregate_version=1,
        payload={
            "candidate_id": candidate,
            "organization_id": uuid4(),
            "invitation_id": invitation,
            "consent_id": consent,
        },
    )
    body, headers = Signatures.from_settings(hiring).sign(event)
    from reverse_hr.services.privacy.domain.privacy import process_accepted_invitation

    attempts = []

    def once_failed(session, incoming):
        attempts.append(incoming.event_id)
        if len(attempts) == 1:
            raise OperationalError("synthetic temporary failure", {}, Exception())
        return process_accepted_invitation(session, incoming)

    monkeypatch.setattr(
        "reverse_hr.services.privacy.consumer.process_accepted_invitation", once_failed
    )
    try:
        publisher.basic_publish(
            exchange="events.hiring",
            routing_key=event.event_type,
            body=body,
            mandatory=True,
            properties=pika.BasicProperties(
                delivery_mode=2, message_id=str(event.event_id), headers=headers
            ),
        )
        receive(subscriber, event.event_id, consumer)
        receive(subscriber, event.event_id, consumer)
        assert attempts == [event.event_id, event.event_id]
        with Session(engine) as session:
            assert (
                session.scalar(
                    select(ContactGrant).where(ContactGrant.invitation_id == str(invitation))
                ).status
                == "active"
            )
    finally:
        producer_connection.close()
        consumer_connection.close()
        engine.dispose()


def test_real_signed_deletion_ack_routes_to_privacy():
    from reverse_hr.services.privacy.domain.privacy import (
        DeletionRequest,
        DeletionTarget,
        PrivacySubject,
    )
    from reverse_hr.shared.event_transport import publish

    candidate, privacy = settings("candidate"), settings("privacy")
    command.upgrade(migration_config(privacy), "head")
    engine = make_engine(privacy.database_url.get_secret_value())
    producer_connection, publisher = connect(candidate)
    consumer_connection, subscriber = connect(privacy)
    subject, request_id = uuid4(), uuid4()
    consumer = PrivacyConsumer(engine, Signatures.from_settings(privacy), privacy)
    try:
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
        body, headers = Signatures.from_settings(candidate).sign(event)
        for _ in range(2):
            publish(
                publisher, "events.candidate", event.event_type, body, headers, str(event.event_id)
            )
            receive(subscriber, event.event_id, consumer)
        with Session(engine) as session:
            target = session.get(DeletionTarget, (str(request_id), "candidate"))
            assert target.status == "deleted"
            assert target.acknowledged_at is not None
    finally:
        producer_connection.close()
        consumer_connection.close()
        engine.dispose()


def test_real_privacy_request_candidate_erasure_and_ack():
    from fastapi.testclient import TestClient

    from reverse_hr.platform.app import create_app
    from reverse_hr.services.candidate.consumer import CandidateConsumer
    from reverse_hr.services.candidate.domain.candidate import CandidateProfile, CandidateSubject
    from reverse_hr.services.privacy.domain.privacy import DeletionTarget
    from reverse_hr.shared.auth import Principal, authenticated
    from reverse_hr.shared.db import IdempotencyRecord, Outbox

    candidate, privacy = settings("candidate"), settings("privacy")
    for config in (candidate, privacy):
        command.upgrade(migration_config(config), "head")
    apps = {config.service_name: create_app(config) for config in (candidate, privacy)}
    subject = uuid4()
    for app in apps.values():
        app.dependency_overrides[authenticated] = lambda: Principal(
            subject, frozenset({"candidate"}), False
        )
    candidate_connection, candidate_channel = connect(candidate)
    privacy_connection, privacy_channel = connect(privacy)
    candidate_signatures, privacy_signatures = (
        Signatures.from_settings(candidate),
        Signatures.from_settings(privacy),
    )
    candidate_engine, privacy_engine = apps["candidate"].state.engine, apps["privacy"].state.engine

    def publish_until(engine, channel, signing, config, event_id):
        for _ in range(200):
            with Session(engine) as session:
                row = session.get(Outbox, str(event_id))
                if row.status == "published":
                    return
                assert row.status == "pending"
            assert publish_one(engine, channel, signing, config)
        raise AssertionError("Test outbox backlog exceeded limit")

    try:
        with (
            TestClient(apps["candidate"]) as candidate_client,
            TestClient(apps["privacy"]) as privacy_client,
        ):
            body = {
                "display_name": "Synthetic",
                "specialization": "backend",
                "declared_grade": "junior",
            }
            assert (
                candidate_client.post(
                    "/v1/candidates/me", json=body, headers={"Idempotency-Key": "create"}
                ).status_code
                == 201
            )
            response = privacy_client.post(
                "/v1/deletion-requests", headers={"Idempotency-Key": "delete"}
            )
            assert response.status_code == 202
            request_id = response.json()["request_id"]
            with Session(privacy_engine) as session:
                request_event = next(
                    row
                    for row in session.scalars(select(Outbox))
                    if row.envelope["event_type"] == "privacy.deletion_requested.v1"
                    and row.envelope["aggregate_id"] == request_id
                )
                request_event_id = request_event.event_id
            publish_until(
                privacy_engine, privacy_channel, privacy_signatures, privacy, request_event_id
            )
            receive(
                candidate_channel,
                request_event_id,
                CandidateConsumer(candidate_engine, candidate_signatures, candidate),
                queue="candidate.incoming",
            )
            with Session(candidate_engine) as session:
                assert session.get(CandidateProfile, str(subject)) is None
                assert session.get(CandidateSubject, str(subject)).blocked
                assert not list(
                    session.scalars(
                        select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
                    )
                )
                ack = next(
                    row
                    for row in session.scalars(select(Outbox))
                    if row.envelope["event_type"] == "candidate.data_deleted.v1"
                    and row.envelope["aggregate_id"] == request_id
                )
                ack_id = ack.event_id
            publish_until(
                candidate_engine, candidate_channel, candidate_signatures, candidate, ack_id
            )
            receive(
                privacy_channel,
                ack_id,
                PrivacyConsumer(privacy_engine, privacy_signatures, privacy),
            )
            result = privacy_client.get("/v1/deletion-requests/me").json()
            assert result["services"]["candidate"] == "deleted"
            assert result["status"] == "in_progress"
            assert (
                candidate_client.post(
                    "/v1/candidates/me", json=body, headers={"Idempotency-Key": "create"}
                ).status_code
                == 409
            )
            with Session(privacy_engine) as session:
                assert session.get(DeletionTarget, (request_id, "candidate")).acknowledged_at
    finally:
        candidate_connection.close()
        privacy_connection.close()
        for app in apps.values():
            app.state.engine.dispose()


def test_real_employer_restriction_confirmation_to_privacy():
    from fastapi.testclient import TestClient

    from reverse_hr.platform.app import create_app
    from reverse_hr.services.employer.consumer import EmployerConsumer
    from reverse_hr.services.employer.domain.employer import Membership, Organization
    from reverse_hr.shared.auth import Principal, authenticated
    from reverse_hr.shared.db import Outbox
    from reverse_hr.shared.event_transport import publish

    employer, privacy = settings("employer"), settings("privacy")
    for config in (employer, privacy):
        command.upgrade(migration_config(config), "head")
    employer_engine = make_engine(employer.database_url.get_secret_value())
    app = create_app(privacy)
    subject, organization_id = uuid4(), uuid4()
    app.dependency_overrides[authenticated] = lambda: Principal(
        subject, frozenset({"candidate"}), False
    )
    employer_connection, employer_channel = connect(employer)
    privacy_connection, privacy_channel = connect(privacy)
    employer_signatures, privacy_signatures = (
        Signatures.from_settings(employer),
        Signatures.from_settings(privacy),
    )
    try:
        with Session(employer_engine) as session, session.begin():
            session.add(
                Organization(
                    organization_id=str(organization_id),
                    name="Synthetic",
                    verification_status="pending",
                    version=1,
                )
            )
            session.add(
                Membership(
                    membership_id=str(uuid4()),
                    organization_id=str(organization_id),
                    subject=str(subject),
                    role="recruiter",
                )
            )
        with TestClient(app) as client:
            result = client.post("/v1/deletion-requests", headers={"Idempotency-Key": "delete"})
            assert result.status_code == 202
            request_id = result.json()["request_id"]
            with Session(app.state.engine) as session:
                request_event = next(
                    EventEnvelope.model_validate(row.envelope)
                    for row in session.scalars(select(Outbox))
                    if row.envelope["event_type"] == "privacy.deletion_requested.v1"
                    and row.envelope["aggregate_id"] == request_id
                )
            body, headers = privacy_signatures.sign(request_event)
            for _ in range(2):
                publish(
                    privacy_channel,
                    "events.privacy",
                    request_event.event_type,
                    body,
                    headers,
                    str(request_event.event_id),
                )
                receive(
                    employer_channel,
                    request_event.event_id,
                    EmployerConsumer(employer_engine, employer_signatures, employer),
                    queue="employer.incoming",
                )
            with Session(employer_engine) as session:
                membership = session.scalar(
                    select(Membership).where(Membership.subject == str(subject))
                )
                assert membership.status == "revoked"
                ack = next(
                    EventEnvelope.model_validate(row.envelope)
                    for row in session.scalars(select(Outbox))
                    if row.envelope["event_type"] == "employer.data_restricted.v1"
                    and row.envelope["aggregate_id"] == request_id
                )
            body, headers = employer_signatures.sign(ack)
            publish(
                employer_channel,
                "events.employer",
                ack.event_type,
                body,
                headers,
                str(ack.event_id),
            )
            receive(
                privacy_channel,
                ack.event_id,
                PrivacyConsumer(app.state.engine, privacy_signatures, privacy),
            )
            progress = client.get("/v1/deletion-requests/me").json()
            assert progress["services"]["employer"] == "restricted"
            assert progress["status"] == "in_progress"
    finally:
        employer_connection.close()
        privacy_connection.close()
        employer_engine.dispose()
        app.state.engine.dispose()
