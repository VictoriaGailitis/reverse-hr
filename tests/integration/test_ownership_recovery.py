import os
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
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
from reverse_hr.services.employer.domain.employer import (
    EmployerSubject,
    Membership,
    Organization,
    OwnershipRecovery,
    process_deletion_request,
)
from reverse_hr.shared.db import IdempotencyRecord, Outbox


def deletion(subject):
    request_id = uuid4()
    return EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )


def headers(auth, key, version):
    return auth | {"Idempotency-Key": key, "If-Match": f'"{version}"'}


@pytest.fixture(params=["sqlite", "postgres"])
def employer(request, service, keys):
    if request.param == "sqlite":
        yield service("employer")
        return
    url = os.getenv("HR_TEST_EMPLOYER_DATABASE_URL")
    if not url:
        pytest.skip("Employer PostgreSQL not configured")
    settings = Settings(service_name="employer", database_url=url)
    command.upgrade(migration_config(settings), "head")
    app = create_app(settings)
    app.state.processing_access = SimpleNamespace(check=lambda *_: None)
    app.state.token_verifier.jwks.fetch_data = lambda: {"keys": [keys[1]]}
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client)


@pytest.fixture
def setup(employer, token):
    owner, colleague, reviewer = uuid4(), uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations",
        json={"name": "Synthetic recovery"},
        headers=headers(auth, "org", 1),
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    member = employer.client.post(
        path + "/members",
        headers=headers(auth, "add", 1),
        json={"subject": str(colleague), "role": "technical_expert"},
    ).json()
    event = deletion(owner)
    with Session(employer.app.state.engine) as session, session.begin():
        process_deletion_request(session, event)
    return SimpleNamespace(
        owner=owner,
        colleague=colleague,
        reviewer=reviewer,
        event=event,
        org=org,
        path=path,
        member=member,
        auth=token(reviewer, ("company_moderator",), amr=["mfa"]),
        body={"membership_id": member["membership_id"], "reason": "Verified corporate request"},
    )


def test_recovery_preserves_restriction_and_restores_management(employer, setup, token):
    s = setup
    path = s.path + "/ownership-recovery"
    reply = employer.client.post(path, json=s.body, headers=headers(s.auth, "recover", 3))
    assert reply.status_code == 200
    assert reply.json()["version"] == 4
    assert (
        employer.client.post(
            path,
            json=s.body,
            headers=headers(s.auth, "recover", 3),
        ).json()
        == reply.json()
    )
    assert (
        employer.client.post(
            path,
            json=s.body,
            headers=headers(s.auth, "another", 4),
        ).status_code
        == 409
    )
    new_owner = token(s.colleague, ("employer",))
    assert (
        employer.client.post(
            s.path + "/members",
            headers=headers(new_owner, "new-member", 4),
            json={"subject": str(uuid4()), "role": "recruiter"},
        ).status_code
        == 201
    )
    assert employer.client.get(s.path, headers=token(s.owner, ("employer",))).status_code == 409
    with Session(employer.app.state.engine) as session, session.begin():
        # A later duplicate request neither restores the owner nor fabricates deleted.
        process_deletion_request(session, s.event.model_copy(update={"event_id": uuid4()}))
        old = session.scalar(select(Membership).where(Membership.subject == str(s.owner)))
        new = session.get(Membership, s.member["membership_id"])
        assert (old.status, old.role, old.version) == ("revoked", "recruiter", 3)
        assert (new.status, new.role, new.version) == ("active", "owner", 2)
        assert session.get(EmployerSubject, str(s.owner)).status == "restricted"
        history = list(
            session.scalars(
                select(OwnershipRecovery).where(
                    OwnershipRecovery.organization_id == s.org["organization_id"],
                )
            )
        )
        assert len(history) == 1 and history[0].reason == s.body["reason"]
        events = [
            row.envelope
            for row in session.scalars(select(Outbox))
            if row.envelope["aggregate_id"] == s.org["organization_id"]
            and row.envelope["event_type"] == "employer.ownership_recovered.v1"
        ]
        assert len(events) == 1
        assert set(events[0]["payload"]) == {"organization_id", "recovery_id"}
    with Session(employer.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.reviewer))
        assert session.get(EmployerSubject, str(s.reviewer)).status == "restricted"
    assert (
        employer.client.post(
            path,
            json=s.body,
            headers=headers(s.auth, "recover", 3),
        ).status_code
        == 409
    )


def test_recovery_rejects_roles_versions_and_unavailable_target(employer, setup, token):
    s = setup
    path = s.path + "/ownership-recovery"
    for auth in (token(s.colleague, ("employer",)), token(s.reviewer, ("company_moderator",))):
        assert (
            employer.client.post(path, json=s.body, headers=headers(auth, "denied", 3)).status_code
            == 403
        )
    assert (
        employer.client.post(path, json=s.body, headers=headers(s.auth, "stale", 2)).status_code
        == 409
    )
    assert (
        employer.client.post(
            path, json=s.body | {"reason": "   "}, headers=headers(s.auth, "blank", 3)
        ).status_code
        == 422
    )
    assert (
        employer.client.post(
            path,
            json=s.body | {"membership_id": str(uuid4())},
            headers=headers(s.auth, "missing", 3),
        ).status_code
        == 404
    )

    def unavailable(subject):
        if str(subject) == str(s.colleague):
            raise HTTPException(503)

    employer.app.state.processing_access.check = unavailable
    assert (
        employer.client.post(
            path, json=s.body, headers=headers(s.auth, "unavailable", 3)
        ).status_code
        == 503
    )
    with Session(employer.app.state.engine) as session:
        assert session.get(Organization, s.org["organization_id"]).version == 3
        assert session.get(Membership, s.member["membership_id"]).role == "technical_expert"
        assert not list(
            session.scalars(
                select(OwnershipRecovery).where(
                    OwnershipRecovery.organization_id == s.org["organization_id"]
                )
            )
        )
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(s.reviewer))
            )
        )
    employer.app.state.processing_access.check = lambda *_: None
    with Session(employer.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.colleague))
    assert (
        employer.client.post(path, json=s.body, headers=headers(s.auth, "blocked", 4)).status_code
        == 409
    )


def test_recovery_cannot_replace_active_owner(employer, token):
    owner, reviewer = uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", json={"name": "Active"}, headers=headers(auth, "org", 1)
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    member = employer.client.post(
        path + "/members",
        json={"subject": str(uuid4()), "role": "recruiter"},
        headers=headers(auth, "add", 1),
    ).json()
    assert (
        employer.client.post(
            path + "/ownership-recovery",
            json={"membership_id": member["membership_id"], "reason": "Synthetic"},
            headers=headers(token(reviewer, ("company_moderator",), amr=["mfa"]), "recover", 2),
        ).status_code
        == 409
    )


def test_competing_recoveries_promote_only_one_owner(employer, setup, token):
    if employer.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Row locking requires PostgreSQL")
    s = setup
    from threading import Barrier

    barrier = Barrier(2)

    # Simultaneous requests with different keys and the same organization version.
    def run(key):
        barrier.wait(timeout=5)
        return employer.client.post(
            s.path + "/ownership-recovery", json=s.body, headers=headers(s.auth, key, 3)
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, ["first", "second"]))
    assert sorted(results) == [200, 409]
    with Session(employer.app.state.engine) as session:
        owners = list(
            session.scalars(
                select(Membership).where(
                    Membership.organization_id == s.org["organization_id"],
                    Membership.role == "owner",
                    Membership.status == "active",
                )
            )
        )
        assert len(owners) == 1


def test_recovery_rolls_back_when_response_check_fails(employer, setup, token):
    s = setup
    original_reviewer = uuid4()
    verify = employer.client.post(
        s.path + "/verification",
        json={"status": "verified", "reason": "Synthetic verification"},
        headers=headers(token(original_reviewer, ("company_moderator",), amr=["mfa"]), "verify", 3),
    )
    assert verify.status_code == 200

    def unavailable(subject):
        if subject == original_reviewer:
            raise HTTPException(503)

    employer.app.state.processing_access.check = unavailable
    assert (
        employer.client.post(
            s.path + "/ownership-recovery",
            json=s.body,
            headers=headers(s.auth, "rollback", 4),
        ).status_code
        == 503
    )
    with Session(employer.app.state.engine) as session:
        assert session.get(Organization, s.org["organization_id"]).version == 4
        assert session.get(Membership, s.member["membership_id"]).role == "technical_expert"
        assert (
            session.scalar(select(Membership).where(Membership.subject == str(s.owner))).role
            == "owner"
        )
        assert not list(
            session.scalars(
                select(OwnershipRecovery).where(
                    OwnershipRecovery.organization_id == s.org["organization_id"]
                )
            )
        )
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(s.reviewer))
            )
        )
        assert not [
            row
            for row in session.scalars(select(Outbox))
            if row.envelope["aggregate_id"] == s.org["organization_id"]
            and row.envelope["event_type"] == "employer.ownership_recovered.v1"
        ]


def test_recovery_racing_target_deletion_leaves_no_active_owner(employer, setup):
    if employer.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Row locking requires PostgreSQL")
    from threading import Barrier

    s = setup
    barrier = Barrier(2)
    event = deletion(s.colleague)

    def recover():
        barrier.wait(timeout=5)
        return employer.client.post(
            s.path + "/ownership-recovery", json=s.body, headers=headers(s.auth, "race", 3)
        ).status_code

    def restrict():
        barrier.wait(timeout=5)
        with Session(employer.app.state.engine) as session, session.begin():
            return process_deletion_request(session, event)

    with ThreadPoolExecutor(max_workers=2) as pool:
        recovered, removed = pool.submit(recover), pool.submit(restrict)
        assert recovered.result(timeout=10) in (200, 409)
        assert removed.result(timeout=10)
    with Session(employer.app.state.engine) as session:
        assert session.get(EmployerSubject, str(s.colleague)).blocked
        assert not list(
            session.scalars(
                select(Membership).where(
                    Membership.organization_id == s.org["organization_id"],
                    Membership.role == "owner",
                    Membership.status == "active",
                )
            )
        )


def test_ownership_history_downgrade_is_protected(service, token):
    employer = service("employer")
    # Empty recovery history can be downgraded and upgraded safely.
    config = migration_config(employer.app.state.settings)
    command.downgrade(config, "0004_employer")
    command.upgrade(config, "head")
    with Session(employer.app.state.engine) as session, session.begin():
        from datetime import UTC, datetime

        session.add(
            OwnershipRecovery(
                recovery_id=str(uuid4()),
                organization_id=str(uuid4()),
                previous_membership_id=str(uuid4()),
                new_membership_id=str(uuid4()),
                reviewer_id=str(uuid4()),
                reason="Synthetic",
                organization_version=1,
                decided_at=datetime.now(UTC),
            )
        )
    # Newer heads preflight the entire path before dropping any tables.
    with pytest.raises(RuntimeError, match="populated"):
        command.downgrade(config, "0004_employer")
    assert employer.client.get("/health/ready").status_code == 200
