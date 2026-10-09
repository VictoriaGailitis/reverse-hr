"""Trust and sanctions through migrated services and real signed membership RPC."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_event_transport import signatures as signatures_fixture
from test_hiring_dialogs import flow as dialog_flow
from test_matching_hiring import setup as market_setup

from reverse_hr.domains.employer_trust import Sanction, TrustAppeal, TrustDecision
from reverse_hr.domains.hiring_trust import EmployerReview

signatures = signatures_fixture
setup = market_setup
flow = dialog_flow


def path(s):
    return f"/v1/organizations/{s.organization_id}"


def sanction(s, auth=None, version=2):
    return s.employer.client.post(
        path(s) + "/sanctions",
        json={"reason": "Repeated abusive conduct", "duration_days": 7},
        headers=headers(auth or s.moderator, "sanction", version),
    )


def test_split_checks_independence_history_and_permissions(setup):
    s = setup
    p = path(s)

    def member():
        return s.matching.app.state.market_access.fetch(
            "employer",
            "membership",
            candidate_id=s.recruiter_id,
            actor_id=s.recruiter_id,
            organization_id=s.organization_id,
        ).allowed

    assert member()
    bad = s.token(s.recruiter_id, ("company_moderator",), amr=["mfa"])
    body = {
        "dimension": "legal",
        "status": "verified",
        "reason": "Manual evidence checked",
        "facts": {
            "legal_name": "Example",
            "tax_id": "1234567890",
            "registry_reference": "manual:doc-1",
        },
    }
    assert (
        s.employer.client.post(
            p + "/trust-checks", json=body, headers=headers(bad, "bad", 2)
        ).status_code
        == 403
    )
    first = s.employer.client.post(
        p + "/trust-checks", json=body, headers=headers(s.moderator, "legal", 2)
    )
    assert first.status_code == 200, first.text
    assert not member()
    second = s.employer.client.post(
        p + "/trust-checks",
        json=body
        | {
            "dimension": "representative",
            "facts": {
                "representative_subject": str(s.recruiter_id),
                "corporate_domain": "example.test",
                "evidence_reference": "manual:authority-1",
            },
        },
        headers=headers(s.moderator, "representative", 3),
    )
    assert second.status_code == 200, second.text
    assert member()
    rows = s.employer.client.get(p + "/trust", headers=s.employer_auth).json()["checks"]
    assert [r["dimension"] for r in rows] == ["legal", "representative"]
    assert all(
        r["reviewer_id"] and r["source"] == "manual_review" and r["decided_at"] for r in rows
    )


def test_sanction_blocks_signed_permission_expiry_restores_and_appeal(setup):
    s = setup
    p = path(s)
    result = sanction(s)
    assert result.status_code == 201, result.text
    sid = result.json()["sanction_id"]
    assert sanction(s).json() == result.json()

    def permission():
        return s.matching.app.state.market_access.fetch(
            "employer",
            "membership",
            candidate_id=s.recruiter_id,
            actor_id=s.recruiter_id,
            organization_id=s.organization_id,
        ).allowed

    assert not permission()
    # History remains while expiry changes the live business permission.
    with Session(s.employer.app.state.engine) as session, session.begin():
        session.get(Sanction, sid).ends_at = datetime.now(UTC) - timedelta(seconds=1)
    assert permission()
    with Session(s.employer.app.state.engine) as session, session.begin():
        session.get(Sanction, sid).ends_at = datetime.now(UTC) + timedelta(days=1)
    created = s.employer.client.post(
        p + "/trust-appeals/" + sid,
        json={"reason": "New evidence"},
        headers=headers(s.employer_auth, "appeal"),
    )
    assert created.status_code == 201, created.text
    aid = created.json()["appeal_id"]
    assert (
        s.employer.client.post(
            p + "/trust-appeals/" + sid,
            json={"reason": "New evidence"},
            headers=headers(s.employer_auth, "duplicate"),
        ).status_code
        == 409
    )
    decision_path = p + "/trust-appeals/" + aid + "/decision"
    decision = {"outcome": "overturned", "reason": "Original restriction was unfounded"}
    assert (
        s.employer.client.post(
            decision_path, json=decision, headers=headers(s.moderator, "self", 1)
        ).status_code
        == 403
    )
    independent = s.token(uuid4(), ("company_moderator",), amr=["mfa"])
    resolved = s.employer.client.post(
        decision_path, json=decision, headers=headers(independent, "resolve", 1)
    )
    assert resolved.status_code == 200, resolved.text
    assert permission()
    with Session(s.employer.app.state.engine) as session:
        assert session.get(Sanction, sid).status == "revoked"
        assert session.get(TrustAppeal, aid).status == "overturned"


def test_review_backed_by_acceptance_safe_publication_response_and_appeal(flow):
    s = flow
    create = s.hiring.client.post(
        f"/v1/invitations/{s.iid}/reviews",
        json={"score": 3, "experience": "communication", "tag": "slow_response"},
        headers=headers(s.auth, "review"),
    )
    assert create.status_code == 201, create.text
    rid = create.json()["review_id"]
    pubpath = f"/v1/organizations/{s.organization_id}/reviews"
    assert s.hiring.client.get(pubpath, headers=s.auth).json() == []
    rp = "/v1/employer-reviews/" + rid
    decision = s.hiring.client.post(
        rp + "/moderation",
        json={"outcome": "published", "reason": "Verified the interaction"},
        headers=headers(s.moderator, "publish", 1),
    )
    assert decision.status_code == 200, decision.text
    public = s.hiring.client.get(pubpath, headers=s.auth)
    assert (
        len(public.json()) == 1
        and str(s.candidate_id) not in public.text
        and s.iid not in public.text
    )
    assert "moderation_reason" not in public.text
    response = s.hiring.client.post(
        rp + "/reply",
        json={"response": "process_improved"},
        headers=headers(s.employer_auth, "reply", 2),
    )
    assert response.status_code == 200, response.text
    appeal = s.hiring.client.post(
        "/v1/moderation-appeals/targets/review/" + rid,
        json={"reason": "Incorrect attribution"},
        headers=headers(s.employer_auth, "appeal"),
    )
    assert appeal.status_code == 201, appeal.text
    aid = appeal.json()["appeal_id"]
    reviewer = s.token(uuid4(), ("company_moderator",), amr=["mfa"])
    resolved = s.hiring.client.post(
        f"/v1/moderation-appeals/{aid}/decision",
        json={"outcome": "overturned", "reason": "Evidence disproves attribution"},
        headers=headers(reviewer, "resolve", 1),
    )
    assert resolved.status_code == 200, resolved.text
    assert s.hiring.client.get(pubpath, headers=s.auth).json() == []
    with Session(s.hiring.app.state.engine) as session:
        assert session.get(EmployerReview, rid).status == "rejected"


@pytest.mark.parametrize("kind", ["no_mfa", "staff", "candidate"])
def test_sanction_privileges(setup, kind):
    s = setup
    auth = (
        s.token(uuid4(), ("company_moderator",))
        if kind == "no_mfa"
        else s.employer_auth
        if kind == "staff"
        else s.auth
    )
    assert sanction(s, auth).status_code == 403


def test_manual_demo_check_forbidden_in_production(setup):
    s = setup
    s.employer.app.state.settings.deployment_mode = "production"
    result = s.employer.client.post(
        path(s) + "/trust-checks",
        json={
            "dimension": "legal",
            "status": "verified",
            "source": "demo_registry",
            "reason": "Synthetic",
            "facts": {
                "legal_name": "Example",
                "tax_id": "1234567890",
                "registry_reference": "demo:1",
            },
        },
        headers=headers(s.moderator, "demo", 2),
    )
    assert result.status_code == 409
    with Session(s.employer.app.state.engine) as session:
        assert session.scalar(select(TrustDecision)) is None


def test_review_and_pending_appeal_are_erased_before_dialogs(flow):
    from test_code_runner import deletion

    from reverse_hr.domains.hiring import process_deletion_request
    from reverse_hr.domains.hiring_trust import ModerationAppeal

    s = flow
    result = s.hiring.client.post(
        f"/v1/invitations/{s.iid}/reviews",
        json={"score": 4, "experience": "communication", "tag": "respectful"},
        headers=headers(s.auth, "review"),
    )
    rid = result.json()["review_id"]
    assert (
        s.hiring.client.post(
            f"/v1/employer-reviews/{rid}/moderation",
            json={"outcome": "published", "reason": "Verified"},
            headers=headers(s.moderator, "publish", 1),
        ).status_code
        == 200
    )
    appeal = s.hiring.client.post(
        "/v1/moderation-appeals/targets/review/" + rid,
        json={"reason": "Disputed"},
        headers=headers(s.employer_auth, "appeal"),
    )
    assert appeal.status_code == 201
    with Session(s.hiring.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate_id))
        assert session.scalar(select(EmployerReview)) is None
        assert session.scalar(select(ModerationAppeal)) is None
    assert (
        s.hiring.client.get(f"/v1/employer-reviews/{rid}", headers=s.moderator).status_code == 404
    )


def test_reviewer_erasure_never_falls_back_to_legacy_verification(setup):
    from types import SimpleNamespace

    from test_code_runner import deletion

    from reverse_hr.domains.employer import Organization, process_deletion_request
    from reverse_hr.domains.employer_trust import permitted

    s = setup
    reviewer = uuid4()
    auth = s.token(reviewer, ("company_moderator",), amr=["mfa"])
    facts = {"legal_name": "Example", "tax_id": "1234567890", "registry_reference": "manual:1"}
    for version, dimension in ((2, "legal"), (3, "representative")):
        body = {
            "dimension": dimension,
            "status": "verified",
            "reason": "Independent evidence",
            "facts": facts
            if dimension == "legal"
            else {
                "representative_subject": str(s.recruiter_id),
                "corporate_domain": "example.test",
                "evidence_reference": "manual:2",
            },
        }
        assert (
            s.employer.client.post(
                path(s) + "/trust-checks", json=body, headers=headers(auth, dimension, version)
            ).status_code
            == 200
        )
    with Session(s.employer.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(reviewer))
        org = session.get(Organization, s.organization_id)
        assert org.trust_required and org.verification_status == "pending"
        assert session.scalar(select(TrustDecision)) is None
        # Even a later legacy moderator approval cannot bypass the new trust rules.
        org.verification_status = "verified"
        assert not permitted(
            session, SimpleNamespace(app=s.employer.app, state=SimpleNamespace()), org
        )


def test_entire_downgrade_path_preserves_readiness_with_legacy_rows(setup):
    from alembic import command

    from reverse_hr.migrate import migration_config

    for target in (setup.employer, setup.hiring):
        with pytest.raises(RuntimeError):
            command.downgrade(migration_config(target.app.state.settings), "base")
        assert target.client.get("/health/ready").status_code == 200


def test_complaint_decision_appeal_requires_new_independent_reviewer(flow):
    from test_hiring_dialogs import deliver_grant, send

    s = flow
    deliver_grant(s)
    message = send(s, auth=s.employer_auth).json()
    complaint = s.hiring.client.post(
        s.path + "/complaints",
        json={"reason": "Complaint", "message_id": message["message_id"]},
        headers=headers(s.auth, "complaint"),
    )
    cid = complaint.json()["complaint_id"]
    assert (
        s.hiring.client.post(
            f"/v1/hiring-complaints/{cid}/decisions",
            json={"outcome": "dismissed", "reason": "Insufficient evidence"},
            headers=headers(s.moderator, "decision", 1),
        ).status_code
        == 200
    )
    appeal = s.hiring.client.post(
        f"/v1/moderation-appeals/targets/complaint/{cid}",
        json={"reason": "Additional context"},
        headers=headers(s.auth, "appeal"),
    )
    assert appeal.status_code == 201, appeal.text
    aid = appeal.json()["appeal_id"]
    body = {"outcome": "overturned", "reason": "Reviewed additional evidence"}
    assert (
        s.hiring.client.post(
            f"/v1/moderation-appeals/{aid}/decision",
            json=body,
            headers=headers(s.moderator, "own", 1),
        ).status_code
        == 403
    )
    independent = s.token(uuid4(), ("company_moderator",), amr=["mfa"])
    resolved = s.hiring.client.post(
        f"/v1/moderation-appeals/{aid}/decision",
        json=body,
        headers=headers(independent, "resolve", 1),
    )
    assert resolved.status_code == 200, resolved.text
    own = s.hiring.client.get(s.path + "/complaints/" + cid, headers=s.auth)
    assert own.json()["status"] == "upheld" and own.json()["version"] == 3
