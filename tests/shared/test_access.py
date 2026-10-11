import time
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
import pytest
from alembic import command
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import HTTPException
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.migrate import migration_config
from reverse_hr.platform.settings import Settings
from reverse_hr.services.employer.domain.employer import Organization
from reverse_hr.services.privacy.domain.privacy import (
    ContactGrant,
    permitted_contact_grant,
    process_accepted_invitation,
)
from reverse_hr.shared.db import Inbox, Outbox


def headers(token, key="command-1", version=None):
    result = token | {"Idempotency-Key": key}
    if version:
        result["If-Match"] = f'"{version}"'
    return result


PROFILE = {"display_name": "Demo", "specialization": "backend", "declared_grade": "middle"}


@pytest.mark.parametrize(
    "overrides",
    [
        {"iss": "https://attacker.example"},
        {"aud": "wrong"},
        {"exp": 1},
        {"typ": "ID"},
        {"email_verified": False},
        {"email_verified": "true"},
        {"sub": "invalid"},
        {"iat": int(time.time()) + 10000},
        {"realm_access": {"roles": "candidate"}},
    ],
)
def test_invalid_tokens_rejected(service, token, overrides):
    client = service("candidate").client
    assert client.get("/v1/candidates/me", headers=token(**overrides)).status_code == 401


def test_missing_forged_and_wrong_signature_rejected(service, token):
    client = service("candidate").client
    assert (
        client.get(
            "/v1/candidates/me", headers={"X-User-ID": str(uuid4()), "X-Role": "candidate"}
        ).status_code
        == 401
    )
    encoded = token()["Authorization"].split()[1]
    claims = jwt.decode(encoded, options={"verify_signature": False})
    forged = jwt.encode(claims, "attacker" * 8, algorithm="HS256", headers={"kid": "test-key"})
    assert (
        client.get("/v1/candidates/me", headers={"Authorization": f"Bearer {forged}"}).status_code
        == 401
    )
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    forged = jwt.encode(claims, other, algorithm="RS256", headers={"kid": "test-key"})
    assert (
        client.get("/v1/candidates/me", headers={"Authorization": f"Bearer {forged}"}).status_code
        == 401
    )


def test_profile_ownership_replay_and_optimistic_version(service, token):
    env = service("candidate")
    owner = token()
    response = env.client.post("/v1/candidates/me", json=PROFILE, headers=headers(owner))
    assert response.status_code == 201
    assert response.json()["confirmed_grade"] is None
    assert (
        env.client.post("/v1/candidates/me", json=PROFILE, headers=headers(owner)).json()
        == response.json()
    )
    assert (
        env.client.post(
            "/v1/candidates/me", json=PROFILE | {"display_name": "Changed"}, headers=headers(owner)
        ).status_code
        == 409
    )
    assert env.client.get("/v1/candidates/me", headers=token()).status_code == 404
    assert (
        env.client.get("/v1/candidates/me", headers=token(roles=("employer",))).status_code == 403
    )
    assert (
        env.client.put("/v1/candidates/me", json=PROFILE, headers=headers(owner, "u1", 1)).json()[
            "version"
        ]
        == 2
    )
    assert (
        env.client.put("/v1/candidates/me", json=PROFILE, headers=headers(owner, "u1", 1)).json()[
            "version"
        ]
        == 2
    )
    assert (
        env.client.put(
            "/v1/candidates/me", json=PROFILE, headers=headers(owner, "u2", 1)
        ).status_code
        == 409
    )
    assert (
        env.client.put(
            "/v1/candidates/me",
            json=PROFILE | {"confirmed_grade": "senior"},
            headers=headers(owner, "u3", 2),
        ).status_code
        == 422
    )
    with Session(env.app.state.engine) as session:
        assert len(list(session.scalars(select(Outbox)))) == 2


def test_consent_owner_version_revoke_and_replay(service, token):
    env = service("privacy")
    owner = token()
    body = {"purpose": "recording", "document_version": "demo-v1"}
    assert (
        env.client.post(
            "/v1/consents", json=body | {"document_version": "invented"}, headers=headers(owner)
        ).status_code
        == 409
    )
    created = env.client.post("/v1/consents", json=body, headers=headers(owner))
    assert created.status_code == 201
    path = f"/v1/consents/{created.json()['consent_id']}/revoke"
    assert env.client.get("/v1/consents", headers=token()).json() == []
    assert env.client.post(path, headers=headers(token(), "revoke", 1)).status_code == 404
    assert env.client.post(path, headers=headers(owner, "revoke", 2)).status_code == 409
    revoked = env.client.post(path, headers=headers(owner, "revoke", 1))
    assert revoked.json()["status"] == "revoked"
    assert env.client.post(path, headers=headers(owner, "revoke", 1)).json() == revoked.json()
    assert env.client.post(path, headers=headers(owner, "again", 1)).status_code == 409
    with Session(env.app.state.engine) as session:
        assert len(list(session.scalars(select(Outbox)))) == 2


def test_organization_membership_and_moderation(service, token):
    env = service("employer")
    owner = token(roles=("employer",))
    created = env.client.post(
        "/v1/organizations", json={"name": "Demo Company"}, headers=headers(owner)
    )
    assert created.status_code == 201
    assert created.json()["verification_status"] == "pending"
    path = f"/v1/organizations/{created.json()['organization_id']}"
    foreign = token(roles=("employer",))
    assert env.client.get(path, headers=foreign).status_code == 404
    assert env.client.get("/v1/organizations", headers=foreign).json() == []
    recruiter_id = uuid4()
    member = {"subject": str(recruiter_id), "role": "recruiter"}
    assert (
        env.client.post(
            path + "/members", json=member, headers=headers(foreign, "m", 1)
        ).status_code
        == 404
    )
    assert (
        env.client.post(path + "/members", json=member, headers=headers(owner, "m", 1)).status_code
        == 201
    )
    recruiter = token(recruiter_id, ("employer",))
    assert env.client.get(path, headers=recruiter).status_code == 200
    assert (
        env.client.post(
            path + "/members",
            json={"subject": str(uuid4()), "role": "recruiter"},
            headers=headers(recruiter, "m", 2),
        ).status_code
        == 403
    )
    verification = {"status": "verified", "reason": "Demo documents manually checked"}
    assert (
        env.client.post(
            path + "/verification", json=verification, headers=headers(owner, "v", 2)
        ).status_code
        == 403
    )
    moderator = token(roles=("company_moderator",))
    assert (
        env.client.post(
            path + "/verification", json=verification, headers=headers(moderator, "v", 2)
        ).status_code
        == 403
    )
    moderator = token(roles=("company_moderator",), amr=["mfa"])
    verified = env.client.post(
        path + "/verification", json=verification, headers=headers(moderator, "v", 2)
    )
    assert verified.status_code == 200
    assert verified.json()["verification_status"] == "verified"
    # A failed duplicate member command rolls back the aggregate-version increment.
    assert (
        env.client.post(
            path + "/members", json=member, headers=headers(owner, "duplicate", 3)
        ).status_code
        == 409
    )
    with Session(env.app.state.engine) as session:
        assert session.get(Organization, created.json()["organization_id"]).version == 3


def test_service_migrations_do_not_create_foreign_tables(service):
    expected = {
        "candidate": "candidate_profiles",
        "privacy": "consents",
        "employer": "organizations",
    }
    for name, own_table in expected.items():
        env = service(name)
        tables = inspect(env.app.state.engine).get_table_names()
        assert own_table in tables
        assert not any(table in tables for other, table in expected.items() if other != name)


def test_moderation_history_preserves_prior_decision(service, token):
    env = service("employer")
    owner = token(roles=("employer",))
    org = env.client.post(
        "/v1/organizations", json={"name": "Synthetic"}, headers=headers(owner)
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    moderator = token(roles=("company_moderator",), amr=["otp"])
    for version, status in ((1, "verified"), (2, "rejected")):
        response = env.client.post(
            path + "/verification",
            json={"status": status, "reason": f"manual decision {version}"},
            headers=headers(moderator, f"verify-{version}", version),
        )
        assert response.status_code == 200
    rows = env.client.get(path + "/verification-history", headers=owner).json()
    assert [row["status"] for row in rows] == ["verified", "rejected"]
    assert [row["organization_version"] for row in rows] == [2, 3]
    assert rows[0]["reason"] == "manual decision 1"
    assert all(row["source"] == "manual_review" for row in rows)
    assert (
        env.client.get(
            path + "/verification-history", headers=token(roles=("employer",))
        ).status_code
        == 404
    )
    assert (
        env.client.get(
            path + "/verification-history", headers=token(roles=("company_moderator",))
        ).status_code
        == 403
    )


def test_revoked_member_loses_access_with_still_valid_token(service, token):
    env = service("employer")
    owner = token(roles=("employer",))
    org = env.client.post(
        "/v1/organizations", json={"name": "Synthetic"}, headers=headers(owner)
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    subject = uuid4()
    employee = token(subject, ("employer",))
    member = env.client.post(
        path + "/members",
        json={"subject": str(subject), "role": "recruiter"},
        headers=headers(owner, "add", 1),
    ).json()
    revoke = f"{path}/members/{member['membership_id']}/revoke"
    assert env.client.get(path, headers=employee).status_code == 200
    assert env.client.post(revoke, headers=headers(employee, "deny", 1)).status_code == 403
    response = env.client.post(revoke, headers=headers(owner, "revoke", 1))
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"
    assert env.client.post(revoke, headers=headers(owner, "revoke", 1)).json() == response.json()
    assert env.client.get(path, headers=employee).status_code == 404
    assert env.client.get("/v1/organizations", headers=employee).json() == []
    assert env.client.get(path + "/members", headers=employee).status_code == 404
    owner_member = next(
        row
        for row in env.client.get(path + "/members", headers=owner).json()
        if row["role"] == "owner"
    )
    assert (
        env.client.post(
            f"{path}/members/{owner_member['membership_id']}/revoke",
            headers=headers(owner, "self", 1),
        ).status_code
        == 409
    )


def accepted(candidate_id, consent_id, organization_id=None):
    invitation_id = uuid4()
    return EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=invitation_id,
        aggregate_version=1,
        payload={
            "candidate_id": candidate_id,
            "organization_id": organization_id or uuid4(),
            "invitation_id": invitation_id,
            "consent_id": consent_id,
        },
    )


def create_disclosure_consent(env, token, subject):
    return env.client.post(
        "/v1/consents",
        json={"purpose": "contact_disclosure", "document_version": "demo-v1"},
        headers=headers(token(subject)),
    ).json()


def test_grant_duplicate_revoke_and_late_event_do_not_restore_access(service, token):
    env = service("privacy")
    subject = uuid4()
    consent = create_disclosure_consent(env, token, subject)
    event = accepted(subject, UUID(consent["consent_id"]))
    with Session(env.app.state.engine) as session, session.begin():
        assert process_accepted_invitation(session, event)
    with Session(env.app.state.engine) as session, session.begin():
        assert not process_accepted_invitation(session, event)
        assert permitted_contact_grant(session, subject, event.payload["organization_id"])
        assert permitted_contact_grant(session, subject, uuid4()) is None
    owner = token(subject)
    grants = env.client.get("/v1/contact-grants", headers=owner).json()
    assert len(grants) == 1
    assert env.client.get("/v1/contact-grants", headers=token()).json() == []
    path = f"/v1/contact-grants/{grants[0]['grant_id']}/revoke"
    assert env.client.post(path, headers=headers(token(), "revoke", 1)).status_code == 404
    assert env.client.post(path, headers=headers(owner, "revoke", 1)).status_code == 200
    later = event.model_copy(update={"event_id": uuid4(), "aggregate_version": 2})
    with Session(env.app.state.engine) as session, session.begin():
        assert process_accepted_invitation(session, later)
        assert permitted_contact_grant(session, subject, event.payload["organization_id"]) is None
        assert len(list(session.scalars(select(ContactGrant)))) == 1
    assert (
        env.client.post(
            "/v1/contact-grants", json=event.model_dump(mode="json"), headers=headers(owner)
        ).status_code
        == 405
    )


def test_consent_revocation_cascades_to_all_linked_company_grants(service, token):
    env = service("privacy")
    subject = uuid4()
    owner = token(subject)
    consent = create_disclosure_consent(env, token, subject)
    events = [accepted(subject, UUID(consent["consent_id"])) for _ in range(2)]
    for event in events:
        with Session(env.app.state.engine) as session, session.begin():
            process_accepted_invitation(session, event)
    path = f"/v1/consents/{consent['consent_id']}/revoke"
    assert env.client.post(path, headers=headers(owner, "revoke", 1)).status_code == 200
    assert all(
        row["status"] == "revoked"
        for row in env.client.get("/v1/contact-grants", headers=owner).json()
    )
    with Session(env.app.state.engine) as session:
        for event in events:
            assert (
                permitted_contact_grant(session, subject, event.payload["organization_id"]) is None
            )
        revoked_events = [
            row
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "privacy.contact_grant_revoked.v1"
        ]
        assert len(revoked_events) == 2
    late = accepted(subject, UUID(consent["consent_id"]))
    with pytest.raises(HTTPException), Session(env.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, late)
    with Session(env.app.state.engine) as session:
        assert session.get(Inbox, ("privacy.accepted_invitation", str(late.event_id))) is None


def test_grants_expire_and_reject_mismatched_basis(service, token):
    env = service("privacy")
    subject = uuid4()
    consent = create_disclosure_consent(env, token, subject)
    mismatch = accepted(uuid4(), UUID(consent["consent_id"]))
    with pytest.raises(HTTPException), Session(env.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, mismatch)
    event = accepted(subject, UUID(consent["consent_id"]))
    with Session(env.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, event, ttl_days=1)
        assert (
            permitted_contact_grant(
                session,
                subject,
                event.payload["organization_id"],
                now=datetime.now(UTC) + timedelta(days=2),
            )
            is None
        )


def test_readiness_rejects_previous_domain_migration(service):
    env = service("privacy")
    settings = Settings(service_name="privacy", database_url=str(env.app.state.engine.url))
    assert env.client.get("/health/ready").status_code == 200
    command.downgrade(migration_config(settings), "0002_privacy")
    assert env.client.get("/health/ready").status_code == 503
    command.upgrade(migration_config(settings), "head")
    assert env.client.get("/health/ready").status_code == 200


def test_deletion_restricts_privacy_and_preserves_pending_targets(service, token):
    from reverse_hr.services.privacy.domain.privacy import (
        ConsentRecord,
        DeletionRequest,
        PrivacySubject,
    )

    privacy = service("privacy")
    subject = uuid4()
    auth = token(subject)
    consent_body = {"purpose": "contact_disclosure", "document_version": "demo-v1"}
    consent = privacy.client.post("/v1/consents", headers=headers(auth), json=consent_body)
    assert consent.status_code == 201
    response = privacy.client.post("/v1/deletion-requests", headers=headers(auth, "delete"))
    assert response.status_code == 202
    result = response.json()
    assert result["status"] == "in_progress"
    assert result["services"]["privacy"] == "restricted"
    assert result["services"]["candidate"] == "pending"
    assert len(result["services"]) == 17
    for key in ("delete", "another-delete"):
        retry = privacy.client.post("/v1/deletion-requests", headers=headers(auth, key))
        assert retry.status_code == 202
        assert retry.json() == result
    # An old idempotency response cannot re-grant or expose an active consent.
    for key in ("command-1", "new-consent"):
        assert (
            privacy.client.post(
                "/v1/consents", headers=headers(auth, key), json=consent_body
            ).status_code
            == 409
        )
    assert privacy.client.get("/v1/consents", headers=auth).status_code == 409
    assert privacy.client.get("/v1/contact-grants", headers=auth).status_code == 409
    assert privacy.client.get("/v1/deletion-requests/me", headers=token()).status_code == 404
    assert privacy.client.get("/v1/deletion-requests/me", headers=auth).json() == result
    with Session(privacy.app.state.engine) as session:
        assert session.get(PrivacySubject, str(subject)).blocked
        assert session.get(ConsentRecord, consent.json()["consent_id"]).status == "revoked"
        assert len(list(session.scalars(select(DeletionRequest)))) == 1
        assert (
            len(
                [
                    row
                    for row in session.scalars(select(Outbox))
                    if row.envelope["event_type"] == "privacy.deletion_requested.v1"
                ]
            )
            == 1
        )


def test_deletion_revokes_grants_and_blocks_late_events(service, token):
    from reverse_hr.services.privacy.domain.privacy import ConsentRecord

    privacy = service("privacy")
    subject, organization, invitation = uuid4(), uuid4(), uuid4()
    auth = token(subject)
    consent = privacy.client.post(
        "/v1/consents",
        headers=headers(auth),
        json={"purpose": "contact_disclosure", "document_version": "demo-v1"},
    ).json()
    event = EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=invitation,
        aggregate_version=1,
        payload={
            "candidate_id": subject,
            "organization_id": organization,
            "invitation_id": invitation,
            "consent_id": UUID(consent["consent_id"]),
        },
    )
    with Session(privacy.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, event)
    assert (
        privacy.client.post("/v1/deletion-requests", headers=headers(auth, "delete")).status_code
        == 202
    )
    with Session(privacy.app.state.engine) as session:
        grant = session.scalar(select(ContactGrant))
        assert grant.status == "revoked" and grant.version == 2
        assert permitted_contact_grant(session, subject, organization) is None
        assert session.get(ConsentRecord, consent["consent_id"]).status == "revoked"
    late = event.model_copy(update={"event_id": uuid4()})
    with (
        pytest.raises(HTTPException) as exc,
        Session(privacy.app.state.engine) as session,
        session.begin(),
    ):
        process_accepted_invitation(session, late)
    assert exc.value.status_code == 409
    with Session(privacy.app.state.engine) as session:
        assert session.get(Inbox, ("privacy.accepted_invitation", str(late.event_id))) is None


def test_deletion_ack_is_bound_to_service_request_and_subject(service, token):
    from reverse_hr.services.privacy.domain.privacy import DeletionTarget, process_deletion_ack

    privacy = service("privacy")
    subject = uuid4()
    auth = token(subject)
    response = privacy.client.post("/v1/deletion-requests", headers=headers(auth)).json()
    request_id = UUID(response["request_id"])
    event = EventEnvelope(
        event_type="candidate.data_deleted.v1",
        producer="candidate",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    invalid = [
        event.model_copy(update={"producer": "employer"}),
        event.model_copy(update={"payload": {"candidate_id": uuid4(), "request_id": request_id}}),
        event.model_copy(update={"aggregate_id": uuid4()}),
        event.model_copy(update={"occurred_at": datetime.now(UTC) - timedelta(days=1)}),
        event.model_copy(update={"occurred_at": datetime.now(UTC) + timedelta(days=1)}),
    ]
    for item in invalid:
        with (
            pytest.raises(HTTPException),
            Session(privacy.app.state.engine) as session,
            session.begin(),
        ):
            process_deletion_ack(session, item)
    with Session(privacy.app.state.engine) as session, session.begin():
        assert process_deletion_ack(session, event)
    with Session(privacy.app.state.engine) as session, session.begin():
        assert not process_deletion_ack(session, event)
        assert process_deletion_ack(session, event.model_copy(update={"event_id": uuid4()}))
    current = privacy.client.get("/v1/deletion-requests/me", headers=auth).json()
    assert current["services"]["candidate"] == "deleted"
    assert current["services"]["employer"] == "pending"
    assert current["status"] == "in_progress"
    with Session(privacy.app.state.engine) as session:
        assert session.get(DeletionTarget, (str(request_id), "candidate")).acknowledged_at


def test_deletion_ledger_downgrade_refuses_to_remove_tombstone(service, token):
    privacy = service("privacy")
    assert privacy.client.post("/v1/deletion-requests", headers=headers(token())).status_code == 202
    config = migration_config(
        Settings(service_name="privacy", database_url=str(privacy.app.state.engine.url))
    )
    with pytest.raises(RuntimeError, match="populated deletion ledger"):
        command.downgrade(config, "0003_privacy")
    assert privacy.client.get("/health/ready").status_code == 200


def candidate_deletion_event(subject, request_id=None):
    request_id = request_id or uuid4()
    return EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )


def test_candidate_deletion_scrubs_profile_responses_and_blocks_replay(service, token):
    from reverse_hr.services.candidate.domain.candidate import (
        CandidateProfile,
        CandidateSubject,
        process_deletion_request,
    )
    from reverse_hr.shared.db import IdempotencyRecord

    candidate = service("candidate")
    subject, other = uuid4(), uuid4()
    auth = token(subject)
    for who in (subject, other):
        assert (
            candidate.client.post(
                "/v1/candidates/me", headers=headers(token(who)), json=PROFILE
            ).status_code
            == 201
        )
    event = candidate_deletion_event(subject)
    with Session(candidate.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, event)
    with Session(candidate.app.state.engine) as session, session.begin():
        assert not process_deletion_request(session, event)
        assert process_deletion_request(session, event.model_copy(update={"event_id": uuid4()}))
    for key in ("command-1", "new-command"):
        assert (
            candidate.client.post(
                "/v1/candidates/me", headers=headers(auth, key), json=PROFILE
            ).status_code
            == 409
        )
    assert (
        candidate.client.put(
            "/v1/candidates/me", headers=headers(auth, "update", 1), json=PROFILE
        ).status_code
        == 409
    )
    assert candidate.client.get("/v1/candidates/me", headers=auth).status_code == 409
    assert candidate.client.get("/v1/candidates/me", headers=token(other)).status_code == 200
    with Session(candidate.app.state.engine) as session:
        assert session.get(CandidateProfile, str(subject)) is None
        assert session.get(CandidateProfile, str(other)) is not None
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
            )
        )
        state = session.get(CandidateSubject, str(subject))
        assert state.blocked and state.deletion_request_id == str(event.aggregate_id)
        acks = [
            row
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "candidate.data_deleted.v1"
        ]
        assert (
            len(acks) == 1
            and acks[0].envelope["payload"] == event.model_dump(mode="json")["payload"]
        )


def test_candidate_deletion_rolls_back_and_rejects_conflicting_requests(service, token):
    from reverse_hr.services.candidate.domain.candidate import (
        CandidateProfile,
        CandidateSubject,
        process_deletion_request,
    )
    from reverse_hr.shared.db import IdempotencyRecord

    candidate = service("candidate")
    subject = uuid4()
    assert (
        candidate.client.post(
            "/v1/candidates/me", headers=headers(token(subject)), json=PROFILE
        ).status_code
        == 201
    )
    event = candidate_deletion_event(subject)
    with (
        pytest.raises(RuntimeError),
        Session(candidate.app.state.engine) as session,
        session.begin(),
    ):
        process_deletion_request(session, event)
        session.flush()
        raise RuntimeError("abort deletion")
    with Session(candidate.app.state.engine) as session:
        assert session.get(CandidateProfile, str(subject)) is not None
        assert not session.get(CandidateSubject, str(subject)).blocked
        assert session.scalar(select(IdempotencyRecord)) is not None
        assert session.get(Inbox, ("candidate.deletion_request", str(event.event_id))) is None
    with Session(candidate.app.state.engine) as session, session.begin():
        process_deletion_request(session, event)
    invalid = [
        candidate_deletion_event(subject),
        event.model_copy(update={"producer": "hiring", "event_id": uuid4()}),
        event.model_copy(update={"aggregate_id": uuid4(), "event_id": uuid4()}),
        event.model_copy(
            update={"occurred_at": datetime.now(UTC) + timedelta(days=1), "event_id": uuid4()}
        ),
    ]
    for message in invalid:
        with (
            pytest.raises(HTTPException),
            Session(candidate.app.state.engine) as session,
            session.begin(),
        ):
            process_deletion_request(session, message)
    config = migration_config(
        Settings(service_name="candidate", database_url=str(candidate.app.state.engine.url))
    )
    with pytest.raises(RuntimeError, match="tombstones"):
        command.downgrade(config, "0002_candidate")
    assert candidate.client.get("/health/ready").status_code == 200


def test_candidate_deletion_without_profile_prevents_first_creation(service, token):
    from reverse_hr.services.candidate.domain.candidate import process_deletion_request

    candidate = service("candidate")
    subject = uuid4()
    with Session(candidate.app.state.engine) as session, session.begin():
        process_deletion_request(session, candidate_deletion_event(subject))
    assert (
        candidate.client.post(
            "/v1/candidates/me", headers=headers(token(subject)), json=PROFILE
        ).status_code
        == 409
    )


def test_employer_restriction_revokes_member_and_scrubs_other_actors_cache(service, token):
    from reverse_hr.services.employer.domain.employer import (
        EmployerSubject,
        Membership,
        process_deletion_request,
    )
    from reverse_hr.shared.db import IdempotencyRecord

    employer = service("employer")
    owner, employee = uuid4(), uuid4()
    owner_auth, employee_auth = token(owner, ("employer",)), token(employee, ("employer",))
    org = employer.client.post(
        "/v1/organizations", headers=headers(owner_auth), json={"name": "Synthetic"}
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    member_body = {"subject": str(employee), "role": "recruiter"}
    member = employer.client.post(
        path + "/members", headers=headers(owner_auth, "add", 1), json=member_body
    ).json()
    event = candidate_deletion_event(employee)
    with Session(employer.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, event)
    with Session(employer.app.state.engine) as session, session.begin():
        assert not process_deletion_request(session, event)
        assert process_deletion_request(session, event.model_copy(update={"event_id": uuid4()}))
    assert employer.client.get(path, headers=employee_auth).status_code == 409
    assert employer.client.get("/v1/organizations", headers=employee_auth).status_code == 409
    assert employer.client.get(path, headers=owner_auth).status_code == 200
    assert [
        item["subject"]
        for item in employer.client.get(path + "/members", headers=owner_auth).json()
    ] == [str(owner)]
    for key in ("add", "new-add"):
        assert (
            employer.client.post(
                path + "/members", headers=headers(owner_auth, key, 3), json=member_body
            ).status_code
            == 409
        )
    with Session(employer.app.state.engine) as session:
        assert session.get(Membership, member["membership_id"]).status == "revoked"
        assert session.get(EmployerSubject, str(employee)).status == "restricted"
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.response.contains(str(employee)))
            )
        )
        events = [
            row.envelope
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "employer.data_restricted.v1"
        ]
        assert len(events) == 1
        assert session.get(Organization, org["organization_id"]).version == 3


def test_employer_owner_restriction_preserves_company_and_blocks_commands(service, token):
    from reverse_hr.services.employer.domain.employer import Membership, process_deletion_request

    employer = service("employer")
    owner, colleague = uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", headers=headers(auth), json={"name": "Synthetic"}
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    assert (
        employer.client.post(
            path + "/members",
            headers=headers(auth, "add", 1),
            json={"subject": str(colleague), "role": "technical_expert"},
        ).status_code
        == 201
    )
    with Session(employer.app.state.engine) as session, session.begin():
        process_deletion_request(session, candidate_deletion_event(owner))
    for key in ("command-1", "fresh"):
        assert (
            employer.client.post(
                "/v1/organizations", headers=headers(auth, key), json={"name": "Synthetic"}
            ).status_code
            == 409
        )
    assert employer.client.get(path, headers=token(colleague, ("employer",))).status_code == 200
    with Session(employer.app.state.engine) as session:
        assert session.get(Organization, org["organization_id"]).name == "Synthetic"
        assert (
            session.scalar(select(Membership).where(Membership.subject == str(colleague))).status
            == "active"
        )
        assert (
            session.scalar(select(Membership).where(Membership.subject == str(owner))).status
            == "revoked"
        )


def test_employer_moderator_records_are_restricted_in_public_views(service, token):
    from reverse_hr.services.employer.domain.employer import (
        VerificationDecision,
        process_deletion_request,
    )

    employer = service("employer")
    owner, reviewer = uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", headers=headers(auth), json={"name": "Synthetic"}
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    moderator = token(reviewer, ("company_moderator",), amr=["mfa"])
    body = {"status": "verified", "reason": "Synthetic decision"}
    assert (
        employer.client.post(
            path + "/verification", headers=headers(moderator, "verify", 1), json=body
        ).status_code
        == 200
    )
    with Session(employer.app.state.engine) as session, session.begin():
        process_deletion_request(session, candidate_deletion_event(reviewer))
    response = employer.client.get(path, headers=auth).json()
    assert response["verified_by"] is None and response["verification_reason"] is None
    assert employer.client.get(path + "/verification-history", headers=auth).json() == []
    assert (
        employer.client.post(
            path + "/verification", headers=headers(moderator, "verify", 1), json=body
        ).status_code
        == 409
    )
    with Session(employer.app.state.engine) as session:
        assert session.scalar(select(VerificationDecision)).reviewer_id == str(reviewer)


def test_employer_empty_subject_deleted_and_rollback_preserves_access(service, token):
    from reverse_hr.services.employer.domain.employer import (
        EmployerSubject,
        process_deletion_request,
    )

    employer = service("employer")
    subject = uuid4()
    event = candidate_deletion_event(subject)
    with (
        pytest.raises(RuntimeError),
        Session(employer.app.state.engine) as session,
        session.begin(),
    ):
        process_deletion_request(session, event)
        session.flush()
        raise RuntimeError("abort")
    with Session(employer.app.state.engine) as session:
        assert session.get(EmployerSubject, str(subject)) is None
        assert session.get(Inbox, ("employer.deletion_request", str(event.event_id))) is None
        assert session.scalar(select(Outbox)) is None
    with Session(employer.app.state.engine) as session, session.begin():
        process_deletion_request(session, event)
    with Session(employer.app.state.engine) as session:
        assert session.get(EmployerSubject, str(subject)).status == "deleted"
        assert session.scalar(select(Outbox)).envelope["event_type"] == "employer.data_deleted.v1"
    config = migration_config(
        Settings(service_name="employer", database_url=str(employer.app.state.engine.url))
    )
    with pytest.raises(RuntimeError, match="restrictions"):
        command.downgrade(config, "0003_employer")
    with (
        pytest.raises(HTTPException),
        Session(employer.app.state.engine) as session,
        session.begin(),
    ):
        process_deletion_request(session, candidate_deletion_event(subject))


def test_privacy_restricted_confirmation_cannot_mark_complete_or_revert_deletion(service, token):
    from reverse_hr.services.privacy.domain.privacy import process_deletion_ack

    privacy = service("privacy")
    subject = uuid4()
    auth = token(subject)
    response = privacy.client.post("/v1/deletion-requests", headers=headers(auth)).json()
    request_id = UUID(response["request_id"])
    event = EventEnvelope(
        event_type="employer.data_restricted.v1",
        producer="employer",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    with Session(privacy.app.state.engine) as session, session.begin():
        process_deletion_ack(session, event)
    result = privacy.client.get("/v1/deletion-requests/me", headers=auth).json()
    assert result["services"]["employer"] == "restricted" and result["status"] == "in_progress"
    with Session(privacy.app.state.engine) as session, session.begin():
        process_deletion_ack(
            session,
            event.model_copy(
                update={"event_id": uuid4(), "event_type": "employer.data_deleted.v1"}
            ),
        )
    with Session(privacy.app.state.engine) as session, session.begin():
        process_deletion_ack(session, event.model_copy(update={"event_id": uuid4()}))
    assert (
        privacy.client.get("/v1/deletion-requests/me", headers=auth).json()["services"]["employer"]
        == "deleted"
    )
