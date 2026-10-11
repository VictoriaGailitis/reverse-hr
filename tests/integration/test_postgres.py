"""Run with a disposable PostgreSQL database (CI provides one)."""

import os
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.app import create_app
from reverse_hr.platform.migrate import migration_config
from reverse_hr.platform.settings import Settings
from reverse_hr.services.candidate.domain.candidate import CandidateProfile
from reverse_hr.services.privacy.domain.privacy import (
    ConsentRecord,
    permitted_contact_grant,
    process_accepted_invitation,
)
from reverse_hr.shared.auth import Principal, authenticated
from reverse_hr.shared.commands import execute
from reverse_hr.shared.db import Outbox, consume_once, enqueue, make_engine


@pytest.mark.skipif(not os.getenv("HR_TEST_POSTGRES_URL"), reason="PostgreSQL not configured")
def test_postgres_migrations_and_transport(monkeypatch):
    url = os.environ["HR_TEST_POSTGRES_URL"]
    monkeypatch.setenv("HR_DATABASE_URL", url)
    command.upgrade(migration_config(), "head")
    engine = make_engine(url)
    event = EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={"candidate_id": uuid4()},
    )
    try:
        with Session(engine) as session, session.begin():
            enqueue(session, event)
        with Session(engine) as session, session.begin():
            assert consume_once(session, "test", event, lambda *_: None)
        with Session(engine) as session, session.begin():
            assert not consume_once(session, "test", event, lambda *_: None)
            stored = session.scalar(select(Outbox).where(Outbox.event_id == str(event.event_id)))
            assert stored.envelope["aggregate_version"] == 1
    finally:
        engine.dispose()


@pytest.mark.skipif(not os.getenv("HR_TEST_POSTGRES_URL"), reason="PostgreSQL not configured")
def test_postgres_concurrent_command_has_one_effect(monkeypatch):
    url = os.environ["HR_TEST_POSTGRES_URL"]
    monkeypatch.setenv("HR_DATABASE_URL", url)
    command.upgrade(migration_config(), "head")
    engine = make_engine(url)
    actor = uuid4()

    def change(session):
        session.add(
            CandidateProfile(
                candidate_id=str(actor),
                display_name="Synthetic",
                specialization="backend",
                declared_grade="junior",
                version=1,
            )
        )
        enqueue(
            session,
            EventEnvelope(
                event_type="candidate.profile_created.v1",
                producer="candidate",
                correlation_id=uuid4(),
                aggregate_id=actor,
                aggregate_version=1,
                payload={"candidate_id": actor},
            ),
        )
        return {"candidate_id": str(actor), "version": 1}

    def run():
        return execute(engine, actor, "create_profile", "concurrent", {"demo": True}, change, 201)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda _: run(), range(2)))
        assert all(response.status_code == 201 for response in responses)
        assert responses[0].body == responses[1].body
        with Session(engine) as session:
            assert session.get(CandidateProfile, str(actor)).version == 1
            matching = [
                row
                for row in session.scalars(select(Outbox))
                if row.envelope["aggregate_id"] == str(actor)
            ]
            assert len(matching) == 1
    finally:
        engine.dispose()


@pytest.mark.skipif(
    not os.getenv("HR_TEST_PRIVACY_POSTGRES_URL"), reason="Privacy PostgreSQL not configured"
)
def test_postgres_acceptance_racing_consent_revoke_fails_closed():
    settings = Settings(
        service_name="privacy", database_url=os.environ["HR_TEST_PRIVACY_POSTGRES_URL"]
    )
    command.upgrade(migration_config(settings), "head")
    app = create_app(settings)
    if settings.service_name == "employer":
        from types import SimpleNamespace

        app.state.processing_access = SimpleNamespace(check=lambda *_: None)
    subject, consent_id, invitation_id, organization_id = (uuid4() for _ in range(4))
    # This test isolates DB concurrency. Signature/claims checks run in test_access.py.
    app.dependency_overrides[authenticated] = lambda: Principal(
        subject, frozenset({"candidate"}), False
    )
    with Session(app.state.engine) as session, session.begin():
        session.add(
            ConsentRecord(
                consent_id=str(consent_id),
                candidate_id=str(subject),
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
        aggregate_id=invitation_id,
        aggregate_version=1,
        payload={
            "candidate_id": subject,
            "organization_id": organization_id,
            "invitation_id": invitation_id,
            "consent_id": consent_id,
        },
    )
    barrier = Barrier(2)

    def accept():
        barrier.wait(timeout=5)
        try:
            with Session(app.state.engine) as session, session.begin():
                process_accepted_invitation(session, event)
            return "accepted"
        except HTTPException as exc:
            assert exc.status_code == 409
            return "blocked"

    with TestClient(app) as client:

        def revoke():
            barrier.wait(timeout=5)
            return client.post(
                f"/v1/consents/{consent_id}/revoke",
                headers={
                    "Idempotency-Key": "race-revoke",
                    "If-Match": '"1"',
                },
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            accepted = pool.submit(accept)
            revoked = pool.submit(revoke)
            assert revoked.result(timeout=10).status_code == 200
            assert accepted.result(timeout=10) in {"accepted", "blocked"}
        with Session(app.state.engine) as session:
            assert session.get(ConsentRecord, str(consent_id)).status == "revoked"
            assert permitted_contact_grant(session, subject, organization_id) is None


@pytest.mark.skipif(
    not os.getenv("HR_TEST_PRIVACY_POSTGRES_URL"), reason="Privacy PostgreSQL not configured"
)
def test_postgres_deletion_racing_new_consent_stays_restricted():
    from reverse_hr.services.privacy.domain.privacy import PrivacySubject

    settings = Settings(
        service_name="privacy", database_url=os.environ["HR_TEST_PRIVACY_POSTGRES_URL"]
    )
    command.upgrade(migration_config(settings), "head")
    app = create_app(settings)
    if settings.service_name == "employer":
        from types import SimpleNamespace

        app.state.processing_access = SimpleNamespace(check=lambda *_: None)
    subject = uuid4()
    app.dependency_overrides[authenticated] = lambda: Principal(
        subject, frozenset({"candidate"}), False
    )
    barrier = Barrier(2)
    with TestClient(app) as client:

        def delete():
            barrier.wait(timeout=5)
            return client.post("/v1/deletion-requests", headers={"Idempotency-Key": "race-delete"})

        def grant():
            barrier.wait(timeout=5)
            return client.post(
                "/v1/consents",
                headers={"Idempotency-Key": "race-grant"},
                json={"purpose": "contact_disclosure", "document_version": "demo-v1"},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            deletion, consent = pool.submit(delete), pool.submit(grant)
            assert deletion.result(timeout=10).status_code == 202
            assert consent.result(timeout=10).status_code in (201, 409)
        assert grant_without_barrier(client).status_code == 409
        with Session(app.state.engine) as session:
            assert session.get(PrivacySubject, str(subject)).blocked
            assert not list(
                session.scalars(
                    select(ConsentRecord).where(
                        ConsentRecord.candidate_id == str(subject), ConsentRecord.status == "active"
                    )
                )
            )


def grant_without_barrier(client):
    return client.post(
        "/v1/consents",
        headers={"Idempotency-Key": "race-grant"},
        json={"purpose": "contact_disclosure", "document_version": "demo-v1"},
    )


@pytest.mark.skipif(not os.getenv("HR_TEST_POSTGRES_URL"), reason="PostgreSQL not configured")
@pytest.mark.parametrize("operation", ["create", "update"])
def test_postgres_candidate_deletion_racing_profile_command(operation):
    from reverse_hr.services.candidate.domain.candidate import (
        CandidateSubject,
        process_deletion_request,
    )
    from reverse_hr.shared.db import IdempotencyRecord

    settings = Settings(service_name="candidate", database_url=os.environ["HR_TEST_POSTGRES_URL"])
    command.upgrade(migration_config(settings), "head")
    app = create_app(settings)
    if settings.service_name == "employer":
        from types import SimpleNamespace

        app.state.processing_access = SimpleNamespace(check=lambda *_: None)
    subject, request_id = uuid4(), uuid4()
    app.dependency_overrides[authenticated] = lambda: Principal(
        subject, frozenset({"candidate"}), False
    )
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    body = {"display_name": "Synthetic", "specialization": "backend", "declared_grade": "junior"}
    barrier = Barrier(2)
    with TestClient(app) as client:
        if operation == "update":
            assert (
                client.post(
                    "/v1/candidates/me", json=body, headers={"Idempotency-Key": "initial"}
                ).status_code
                == 201
            )

        def remove():
            barrier.wait(timeout=5)
            with Session(app.state.engine) as session, session.begin():
                return process_deletion_request(session, event)

        def change():
            barrier.wait(timeout=5)
            if operation == "create":
                return client.post(
                    "/v1/candidates/me", json=body, headers={"Idempotency-Key": "race"}
                )
            return client.put(
                "/v1/candidates/me",
                json=body,
                headers={"Idempotency-Key": "race", "If-Match": '"1"'},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            deletion, command_result = pool.submit(remove), pool.submit(change)
            assert deletion.result(timeout=10)
            assert command_result.result(timeout=10).status_code in (200, 201, 409)
        assert (
            client.post(
                "/v1/candidates/me", json=body, headers={"Idempotency-Key": "race"}
            ).status_code
            == 409
        )
        with Session(app.state.engine) as session:
            assert session.get(CandidateProfile, str(subject)) is None
            assert session.get(CandidateSubject, str(subject)).blocked
            assert not list(
                session.scalars(
                    select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
                )
            )


@pytest.mark.skipif(
    not os.getenv("HR_TEST_EMPLOYER_DATABASE_URL"), reason="Employer PostgreSQL not configured"
)
def test_postgres_employer_restriction_racing_membership_creation():
    from reverse_hr.services.employer.domain.employer import (
        EmployerSubject,
        Membership,
        process_deletion_request,
    )

    settings = Settings(
        service_name="employer", database_url=os.environ["HR_TEST_EMPLOYER_DATABASE_URL"]
    )
    command.upgrade(migration_config(settings), "head")
    app = create_app(settings)
    if settings.service_name == "employer":
        from types import SimpleNamespace

        app.state.processing_access = SimpleNamespace(check=lambda *_: None)
    owner, subject, request_id = uuid4(), uuid4(), uuid4()
    app.dependency_overrides[authenticated] = lambda: Principal(
        owner, frozenset({"employer"}), False
    )
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    barrier = Barrier(2)
    with TestClient(app) as client:
        org = client.post(
            "/v1/organizations", json={"name": "Synthetic"}, headers={"Idempotency-Key": "org"}
        ).json()
        path = f"/v1/organizations/{org['organization_id']}/members"

        def restrict():
            barrier.wait(timeout=5)
            with Session(app.state.engine) as session, session.begin():
                return process_deletion_request(session, event)

        def add():
            barrier.wait(timeout=5)
            return client.post(
                path,
                json={"subject": str(subject), "role": "recruiter"},
                headers={"Idempotency-Key": "add", "If-Match": '"1"'},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            removed, created = pool.submit(restrict), pool.submit(add)
            assert removed.result(timeout=10)
            assert created.result(timeout=10).status_code in (201, 409)
        with Session(app.state.engine) as session:
            assert session.get(EmployerSubject, str(subject)).blocked
            assert not list(
                session.scalars(
                    select(Membership).where(
                        Membership.subject == str(subject), Membership.status == "active"
                    )
                )
            )


@pytest.mark.skipif(
    not os.getenv("HR_TEST_PRIVACY_POSTGRES_URL"), reason="Privacy PostgreSQL not configured"
)
def test_postgres_last_acknowledgements_complete_cleanup_once():
    from reverse_hr.platform.settings import SERVICES
    from reverse_hr.services.privacy.domain.privacy import (
        DeletionRequest,
        PrivacySubject,
        process_deletion_ack,
    )

    settings = Settings(
        service_name="privacy", database_url=os.environ["HR_TEST_PRIVACY_POSTGRES_URL"]
    )
    command.upgrade(migration_config(settings), "head")
    app = create_app(settings)
    subject = uuid4()
    app.dependency_overrides[authenticated] = lambda: Principal(
        subject, frozenset({"candidate"}), False
    )
    external = [name for name in SERVICES if name != "privacy"]
    with TestClient(app) as client:
        assert (
            client.post(
                "/v1/consents",
                json={"purpose": "assessment", "document_version": "demo-v1"},
                headers={"Idempotency-Key": "consent"},
            ).status_code
            == 201
        )
        result = client.post("/v1/deletion-requests", headers={"Idempotency-Key": "delete"}).json()
        from uuid import UUID

        request_id = UUID(result["request_id"])

        def event(name):
            return EventEnvelope(
                event_type=f"{name}.data_deleted.v1",
                producer=name,
                correlation_id=uuid4(),
                aggregate_id=request_id,
                aggregate_version=1,
                payload={"candidate_id": subject, "request_id": request_id},
            )

        for name in external[:-2]:
            with Session(app.state.engine) as session, session.begin():
                process_deletion_ack(session, event(name))
        barrier = Barrier(2)

        def finish(name):
            barrier.wait(timeout=5)
            with Session(app.state.engine) as session, session.begin():
                return process_deletion_ack(session, event(name))

        with ThreadPoolExecutor(max_workers=2) as pool:
            assert all(pool.map(finish, external[-2:]))
        assert client.get("/v1/deletion-requests/me").json()["status"] == "completed"
        with Session(app.state.engine) as session:
            assert session.get(PrivacySubject, str(subject)).blocked
            assert session.get(DeletionRequest, str(request_id)).completed_at is not None
            assert not list(
                session.scalars(
                    select(ConsentRecord).where(ConsentRecord.candidate_id == str(subject))
                )
            )
            completions = [
                row
                for row in session.scalars(select(Outbox))
                if row.envelope["event_type"] == "privacy.deletion_completed.v1"
                and row.envelope["aggregate_id"] == str(request_id)
            ]
            assert len(completions) == 1
