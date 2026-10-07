"""Actual signed RPC through TestClient and migrated service DBs; synthetic grades."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture

from reverse_hr.confirmed_grade_access import DecisionSummary
from reverse_hr.db import Outbox
from reverse_hr.domains.candidate_grades import process_grade_decision
from reverse_hr.domains.hiring import InvitationRow
from reverse_hr.domains.hiring import process_deletion_request as delete_hiring
from reverse_hr.domains.matching import MatchSnapshot, Projection, process_profile_change
from reverse_hr.domains.matching import process_deletion_request as delete_matching
from reverse_hr.domains.privacy import process_accepted_invitation
from reverse_hr.events import EventEnvelope
from reverse_hr.market_access import MarketAccess
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import ProcessingAccess

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures):
    targets = {
        name: service(name) for name in ("privacy", "candidate", "employer", "hiring", "matching")
    }

    def sender(route, raw, signature, *, origin=None, max_bytes=4096):
        owner = origin.split("//")[1].split(":")[0] if origin else "privacy"
        response = targets[owner].client.post(
            "/internal/v1/" + route,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise HTTPException(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    for name, target in targets.items():
        setattr(target.app.state, name + "_signatures", signatures[name])
        if name != "privacy":
            processing = ProcessingAccess(target.app.state.settings)
            processing._signatures, processing._send = signatures[name], sender
            target.app.state.processing_access = processing
        if name in {"candidate", "matching", "hiring"}:
            market = MarketAccess(target.app.state.settings)
            market._signatures, market._send = signatures[name], sender
            target.app.state.market_access = market
    s = SimpleNamespace(
        **targets,
        token=token,
        signatures=signatures,
        sender=sender,
        candidate_id=uuid4(),
        recruiter_id=uuid4(),
    )
    s.auth = token(s.candidate_id)
    s.employer_auth = token(s.recruiter_id, ("employer",))
    s.moderator = token(uuid4(), ("company_moderator",), amr=["mfa"])
    created = s.employer.client.post(
        "/v1/organizations", json={"name": "Example"}, headers=headers(s.employer_auth, "org")
    )
    assert created.status_code == 201, created.text
    s.organization_id = created.json()["organization_id"]
    assert (
        s.employer.client.post(
            f"/v1/organizations/{s.organization_id}/verification",
            json={"status": "verified", "reason": "Synthetic company review"},
            headers=headers(s.moderator, "verify", 1),
        ).status_code
        == 200
    )
    assert (
        s.candidate.client.post(
            "/v1/candidates/me",
            json={
                "display_name": "Candidate",
                "specialization": "backend",
                "declared_grade": "lead",
            },
            headers=headers(s.auth, "profile"),
        ).status_code
        == 201
    )
    grade(s, "middle")
    s.consent = consent(s, "profile_publication")
    published = publication(s, True)
    assert published.status_code == 200, published.text
    refresh(s)
    need = s.hiring.client.post(
        "/v1/hiring-needs",
        json={
            "organization_id": s.organization_id,
            "specialization": "backend",
            "confirmed_grade": "junior",
            "required_skills": ["python"],
            "status": "published",
        },
        headers=headers(s.employer_auth, "need"),
    )
    assert need.status_code == 201, need.text
    s.need = need.json()
    return s


def consent(s, purpose):
    response = s.privacy.client.post(
        "/v1/consents",
        json={"purpose": purpose, "document_version": "demo-v1"},
        headers=headers(s.auth, purpose),
    )
    assert response.status_code == 201, response.text
    return response.json()["consent_id"]


def grade(s, level):
    sid = uuid4()
    event = EventEnvelope(
        producer="assessment",
        event_type="assessment.grade_decision_recorded.v1",
        aggregate_id=sid,
        aggregate_version=5,
        correlation_id=uuid4(),
        payload={
            "candidate_id": s.candidate_id,
            "session_id": sid,
            "decision_id": uuid4(),
            "reviewer_id": uuid4(),
        },
    )
    summary = DecisionSummary(
        specialization="backend",
        target_grade=level,
        status="confirmed",
        decided_at=datetime.now(UTC),
    )
    with Session(s.candidate.app.state.engine) as session, session.begin():
        process_grade_decision(
            session, event, SimpleNamespace(fetch=lambda **_: summary, check=lambda *_: None)
        )


def publication(s, published, key=None):
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    return s.candidate.client.put(
        "/v1/candidates/me/publication",
        json={
            "published": published,
            "consent_id": s.consent if published else None,
            "declared_skills": ["Python"],
        },
        headers=headers(s.auth, key or str(uuid4()), profile["version"]),
    )


def refresh(s, event=None):
    if event is None:
        with Session(s.candidate.app.state.engine) as session:
            messages = [
                EventEnvelope.model_validate(row.envelope)
                for row in session.scalars(select(Outbox))
                if row.envelope["event_type"] == "candidate.profile_updated.v1"
            ]
            event = max(messages, key=lambda e: e.aggregate_version)
    with Session(s.matching.app.state.engine) as session, session.begin():
        return process_profile_change(session, event, s.matching.app.state.market_access)


def matches(s, mode="demo", key=None):
    return s.matching.client.post(
        "/v1/matches",
        json={"need_id": s.need["need_id"], "organization_id": s.organization_id, "mode": mode},
        headers=headers(s.employer_auth, key or str(uuid4())),
    )


def invite(s, key="invite"):
    return s.hiring.client.post(
        "/v1/invitations",
        json={
            "organization_id": s.organization_id,
            "candidate_id": str(s.candidate_id),
            "description": "Backend role",
            "employer_contact": "recruiter@example.test",
            "salary": {"tax_basis": "gross", "minimum": 100000, "maximum": 200000},
        },
        headers=headers(s.employer_auth, key),
    )


def test_signed_matching_demo_filter_saved_snapshot_and_live_publication(setup):
    s = setup
    assert matches(s, "production").json()["matches"] == []
    result = matches(s, key="saved")
    assert result.status_code == 201, result.text
    data = result.json()
    assert len(data["matches"]) == 1
    card = data["matches"][0]
    assert card["confirmed_grade"] == "middle" and card["declared_skills"] == ["python"]
    assert card["score"] == 90 and card["demo"]
    assert not {"email", "phone", "consent_id", "declared_grade"} & card.keys()
    assert matches(s, key="saved").json()["snapshot_id"] == data["snapshot_id"]
    assert publication(s, False).status_code == 200
    assert (
        s.matching.client.get("/v1/matches/" + data["snapshot_id"], headers=s.employer_auth).json()[
            "matches"
        ]
        == []
    )
    assert matches(s, key="saved").json()["matches"] == []
    assert (
        s.matching.client.get(
            "/v1/matches/" + data["snapshot_id"], headers=s.token(uuid4(), ("employer",))
        ).status_code
        == 404
    )


def test_grade_updates_duplicate_and_delayed_events_do_not_downgrade(setup):
    s = setup
    with Session(s.candidate.app.state.engine) as session:
        previous = max(
            [
                EventEnvelope.model_validate(r.envelope)
                for r in session.scalars(select(Outbox))
                if r.envelope["event_type"] == "candidate.profile_updated.v1"
            ],
            key=lambda e: e.aggregate_version,
        )
    grade(s, "senior")
    assert refresh(s)
    assert not refresh(s)
    assert refresh(s, previous.model_copy(update={"event_id": uuid4()}))
    assert matches(s).json()["matches"][0]["confirmed_grade"] == "senior"


def test_company_authorization_requirements_and_closed_need(setup):
    s = setup
    other = s.token(uuid4(), ("employer",))
    assert (
        s.matching.client.post(
            "/v1/matches",
            json={
                "need_id": s.need["need_id"],
                "organization_id": s.organization_id,
                "mode": "demo",
            },
            headers=headers(other),
        ).status_code
        == 409
    )
    result = matches(s).json()
    body = {
        k: s.need[k]
        for k in (
            "organization_id",
            "specialization",
            "confirmed_grade",
            "required_skills",
            "status",
        )
    }
    body["required_skills"] = ["rust"]
    changed = s.hiring.client.put(
        "/v1/hiring-needs/" + s.need["need_id"],
        json=body,
        headers=headers(s.employer_auth, "skills", 1),
    )
    assert changed.status_code == 200, changed.text
    assert matches(s).json()["matches"] == []
    assert (
        s.matching.client.get(
            "/v1/matches/" + result["snapshot_id"], headers=s.employer_auth
        ).status_code
        == 409
    )
    body["status"] = "closed"
    assert (
        s.hiring.client.put(
            "/v1/hiring-needs/" + s.need["need_id"],
            json=body,
            headers=headers(s.employer_auth, "close", 2),
        ).status_code
        == 200
    )
    assert matches(s).status_code == 409


def test_invitation_acceptance_privacy_grant_and_contact_revoke(setup):
    s = setup
    assert (
        s.candidate.client.put(
            "/v1/candidates/me/contacts",
            json={"email": "candidate@example.test", "phone": "+79991234567"},
            headers=headers(s.auth, "contacts"),
        ).status_code
        == 200
    )
    created = invite(s)
    assert created.status_code == 201, created.text
    iid = created.json()["invitation_id"]
    assert invite(s).json()["invitation_id"] == iid
    path = "/v1/invitations/" + iid
    assert s.hiring.client.get(path + "/contacts", headers=s.employer_auth).status_code == 409
    disclosure = consent(s, "contact_disclosure")
    accepted = s.hiring.client.post(
        path + "/accept",
        json={"disclosure_consent_id": disclosure},
        headers=headers(s.auth, "accept", 1),
    )
    assert accepted.status_code == 200, accepted.text
    assert (
        s.hiring.client.post(
            path + "/accept",
            json={"disclosure_consent_id": disclosure},
            headers=headers(s.auth, "accept", 1),
        ).status_code
        == 200
    )
    # An accepted invitation alone cannot disclose a contact until Privacy consumes it.
    assert s.hiring.client.get(path + "/contacts", headers=s.employer_auth).status_code == 409
    with Session(s.hiring.app.state.engine) as session:
        message = next(
            EventEnvelope.model_validate(r.envelope)
            for r in session.scalars(select(Outbox))
            if r.envelope["event_type"] == "hiring.invitation_accepted.v1"
        )
    with Session(s.privacy.app.state.engine) as session, session.begin():
        assert process_accepted_invitation(session, message)
        assert not process_accepted_invitation(session, message)
    contacts = s.hiring.client.get(path + "/contacts", headers=s.employer_auth)
    assert contacts.status_code == 200, contacts.text
    assert contacts.json()["email"] == "candidate@example.test"
    revoked = s.privacy.client.post(
        "/v1/consents/" + disclosure + "/revoke", headers=headers(s.auth, "revoke", 1)
    )
    assert revoked.status_code == 200, revoked.text
    assert s.hiring.client.get(path + "/contacts", headers=s.employer_auth).status_code == 409
    with Session(s.privacy.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, message.model_copy(update={"event_id": uuid4()}))
    assert s.hiring.client.get(path + "/contacts", headers=s.employer_auth).status_code == 409


def test_publication_consent_withdrawal_clears_projection_and_saved_disclosure(setup):
    s = setup
    result = matches(s).json()
    revoked = s.privacy.client.post(
        "/v1/consents/" + s.consent + "/revoke", headers=headers(s.auth, "withdraw-publication", 1)
    )
    assert revoked.status_code == 200, revoked.text
    assert (
        s.matching.client.get(
            "/v1/matches/" + result["snapshot_id"], headers=s.employer_auth
        ).json()["matches"]
        == []
    )
    with Session(s.privacy.app.state.engine) as session:
        event = next(
            EventEnvelope.model_validate(r.envelope)
            for r in session.scalars(select(Outbox))
            if r.envelope["event_type"] == "privacy.consent_revoked.v1"
        )
    assert refresh(s, event)
    with Session(s.matching.app.state.engine) as session:
        assert session.get(Projection, str(s.candidate_id)).card is None
    assert publication(s, True).status_code == 409
    assert invite(s).status_code == 409


def test_erasure_scrubs_snapshots_invites_caches_and_late_events(setup):
    from reverse_hr.db import IdempotencyRecord
    from reverse_hr.domains.candidate import process_deletion_request as delete_candidate

    s = setup
    saved = matches(s).json()
    assert invite(s).status_code == 201
    with Session(s.candidate.app.state.engine) as session:
        profile_event = max(
            [
                EventEnvelope.model_validate(r.envelope)
                for r in session.scalars(select(Outbox))
                if r.envelope["event_type"] == "candidate.profile_updated.v1"
            ],
            key=lambda e: e.aggregate_version,
        )
    event = deletion(s.candidate_id)
    for target, handler in (
        (s.matching, delete_matching),
        (s.hiring, delete_hiring),
        (s.candidate, delete_candidate),
    ):
        with Session(target.app.state.engine) as session, session.begin():
            assert handler(session, event)
            assert not handler(session, event)
    with Session(s.matching.app.state.engine) as session:
        assert session.get(Projection, str(s.candidate_id)) is None
        assert session.scalar(select(MatchSnapshot)) is None
    with Session(s.hiring.app.state.engine) as session:
        assert session.scalar(select(InvitationRow)) is None
        assert (
            session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.response.contains(str(s.candidate_id))
                )
            )
            is None
        )
    assert refresh(s, profile_event.model_copy(update={"event_id": uuid4()}))
    with Session(s.matching.app.state.engine) as session:
        assert session.get(Projection, str(s.candidate_id)) is None
        acks = [
            r
            for r in session.scalars(select(Outbox))
            if r.envelope["event_type"] == "matching.data_deleted.v1"
        ]
        assert len(acks) == 1
    assert (
        s.matching.client.get(
            "/v1/matches/" + saved["snapshot_id"], headers=s.employer_auth
        ).status_code
        == 404
    )
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.matching.app.state.settings), "base")
    assert s.matching.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("action", ["decline", "revoke", "expired"])
def test_invitation_terminal_transitions_and_owner_isolation(setup, action):
    s = setup
    created = invite(s)
    iid = created.json()["invitation_id"]
    path = "/v1/invitations/" + iid
    stranger = s.token(uuid4())
    assert s.hiring.client.get(path, headers=stranger).status_code == 403
    assert s.hiring.client.get("/v1/invitations", headers=s.auth).json()[0]["invitation_id"] == iid
    if action == "expired":
        with Session(s.hiring.app.state.engine) as session, session.begin():
            session.get(InvitationRow, iid).expires_at = datetime.now(UTC) - timedelta(seconds=1)
        assert s.hiring.client.get(path, headers=s.auth).json()["status"] == "expired"
        assert invite(s).json()["status"] == "expired"
        assert (
            s.hiring.client.post(
                path + "/decline", headers=headers(s.auth, "expired", 1)
            ).status_code
            == 409
        )
    else:
        auth = s.auth if action == "decline" else s.employer_auth
        changed = s.hiring.client.post(path + "/" + action, headers=headers(auth, action, 1))
        assert changed.status_code == 200, changed.text
        assert (
            s.hiring.client.post(path + "/" + action, headers=headers(auth, action, 1)).status_code
            == 200
        )
        assert (
            s.hiring.client.post(
                path + "/" + action, headers=headers(auth, "different", 1)
            ).status_code
            == 409
        )
    assert s.hiring.client.get(path + "/contacts", headers=s.employer_auth).status_code == 409


def test_membership_revocation_closes_matching_and_invitation_reads(setup):
    s = setup
    member_id = uuid4()
    actor_id = uuid4()
    created = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json={"subject": str(actor_id), "role": "recruiter"},
        headers=headers(s.employer_auth, "member", 2),
    )
    assert created.status_code == 201, created.text
    member_id = created.json()["membership_id"]
    recruiter = s.token(actor_id, ("employer",))
    saved = matches(s).json()
    path = "/v1/matches/" + saved["snapshot_id"]
    # Snapshot belongs to its requester even when another recruiter shares the company.
    assert s.matching.client.get(path, headers=recruiter).status_code == 404
    query = {"organization_id": s.organization_id, "need_id": s.need["need_id"], "mode": "demo"}
    result = s.matching.client.post(
        "/v1/matches", json=query, headers=headers(recruiter, "recruiter-query")
    )
    assert result.status_code == 201, result.text
    rid = result.json()["snapshot_id"]
    revoke = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members/{member_id}/revoke",
        headers=headers(s.employer_auth, "revoke-member", 1),
    )
    assert revoke.status_code == 200, revoke.text
    assert s.matching.client.get("/v1/matches/" + rid, headers=recruiter).status_code == 409
    assert (
        s.matching.client.post(
            "/v1/matches", json=query, headers=headers(recruiter, "recruiter-query")
        ).status_code
        == 409
    )


@pytest.mark.parametrize("name", ["candidate", "employer", "matching", "hiring"])
def test_empty_market_migration_roundtrip(service, name):
    target = service(name)
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200


def test_same_grade_confirmation_keeps_current_matching_evidence_stable(setup):
    s = setup
    before = matches(s).json()
    evidence = before["matches"][0]["decision_id"]
    grade(s, "middle")
    assert not refresh(s)
    after = matches(s).json()
    assert after["matches"][0]["decision_id"] == evidence
    assert (
        s.matching.client.get(
            "/v1/matches/" + before["snapshot_id"], headers=s.employer_auth
        ).json()["matches"]
        == before["matches"]
    )


def test_recruiter_erasure_scrubs_owned_needs_and_saved_queries(setup):
    from reverse_hr.domains.hiring import Need

    s = setup
    assert matches(s).status_code == 201
    assert invite(s).status_code == 201
    event = deletion(s.recruiter_id)
    for target, handler in ((s.matching, delete_matching), (s.hiring, delete_hiring)):
        with Session(target.app.state.engine) as session, session.begin():
            handler(session, event)
    with Session(s.hiring.app.state.engine) as session:
        assert session.scalar(select(Need)) is None
        assert session.scalar(select(InvitationRow)) is None
    with Session(s.matching.app.state.engine) as session:
        assert session.scalar(select(MatchSnapshot)) is None
    assert matches(s).status_code == 409


def test_no_grade_and_declared_grade_do_not_pass_matching(setup):
    from reverse_hr.domains.candidate_grades import CandidateDecision

    s = setup
    with Session(s.candidate.app.state.engine) as session, session.begin():
        for row in session.scalars(
            select(CandidateDecision).where(CandidateDecision.candidate_id == str(s.candidate_id))
        ):
            session.delete(row)
    assert matches(s).json()["matches"] == []


def test_invalid_salary_and_wrong_contact_permission_cannot_disclose(setup):
    s = setup
    bad = {
        "organization_id": s.organization_id,
        "candidate_id": str(s.candidate_id),
        "description": "Role",
        "employer_contact": "employer@example.test",
        "salary": {"tax_basis": "net", "minimum": 200, "maximum": 100},
    }
    assert (
        s.hiring.client.post(
            "/v1/invitations", json=bad, headers=headers(s.employer_auth, "bad-salary")
        ).status_code
        == 422
    )
    response = invite(s)
    path = "/v1/invitations/" + response.json()["invitation_id"]
    # Publication consent cannot be reused as contact disclosure consent.
    assert (
        s.hiring.client.post(
            path + "/accept",
            json={"disclosure_consent_id": s.consent},
            headers=headers(s.auth, "wrong-consent", 1),
        ).status_code
        == 409
    )
    assert s.hiring.client.get(path, headers=s.auth).json()["status"] == "sent"
