"""Migrated services, fresh signed Need access and reviewed semantic matching policies."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from reverse_hr.contracts.qualification import advice, freshness
from reverse_hr.services.matching.domain.matching_governance import (
    GovernanceVersion,
    IntentPreview,
    ParsedIntent,
    RankingPolicy,
    Vocabulary,
    validate_intent,
)
from tests.integration.test_matching_hiring import setup as matching_fixture
from tests.services.matching.test_matching_qualification import evidence, inject, refresh
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture
setup = matching_fixture


def create_versions(s, *, demo=True):
    admin_id = uuid4()
    s.admin = s.token(admin_id, ("content_admin",), amr=["mfa"])
    s.reviewer = s.token(uuid4(), ("assessment_reviewer",), amr=["mfa"])
    catalog = {
        "version": "test-catalog-v1",
        "demo": demo,
        "specializations": ["backend", "data"],
        "entries": [
            {"key": "python", "aliases": ["питон"], "evidence_keys": ["python"]},
            {
                "key": "postgresql",
                "aliases": ["postgres"],
                "kind": "technology",
                "evidence_keys": ["sql", "query-planning"],
            },
        ],
    }
    response = s.matching.client.post(
        "/v1/matches/governance/catalogs", json=catalog, headers=headers(s.admin, "catalog")
    )
    assert response.status_code == 201, response.text
    s.catalog = response.json()["version_id"]
    decision = {"expected_revision": 1, "decision": "approved", "reason": "Reviewed rubric mapping"}
    assert (
        s.matching.client.post(
            f"/v1/matches/governance/versions/{s.catalog}/decisions",
            json=decision,
            headers=headers(s.admin, "self"),
        ).status_code
        == 403
    )
    response = s.matching.client.post(
        f"/v1/matches/governance/versions/{s.catalog}/decisions",
        json=decision,
        headers=headers(s.reviewer, "catalog-approval"),
    )
    assert response.status_code == 200, response.text
    policy = {
        "version": "test-policy-v1",
        "catalog_id": s.catalog,
        "demo": demo,
        "current_days": 30,
        "expiry_days": 90,
        "calibration_minimum_precision": 0.8,
    }
    response = s.matching.client.post(
        "/v1/matches/governance/policies", json=policy, headers=headers(s.admin, "policy")
    )
    assert response.status_code == 201, response.text
    s.policy = response.json()["version_id"]
    return decision


def approve_policy(s, decision=None):
    response = s.matching.client.post(
        f"/v1/matches/governance/versions/{s.policy}/decisions",
        json=decision
        or {
            "expected_revision": 1,
            "decision": "approved",
            "reason": "Reviewed demo scoring bounds",
        },
        headers=headers(s.reviewer, "policy-approval"),
    )
    assert response.status_code == 200, response.text


def preview(s, *, parser="explicit", text="Нужен postgres"):
    response = s.matching.client.post(
        "/v1/matches/intent-previews",
        json={
            "organization_id": s.organization_id,
            "need_id": s.need["need_id"],
            "catalog_id": s.catalog,
            "text": text,
            "parser": parser,
        },
        headers=headers(s.employer_auth, "preview"),
    )
    assert response.status_code == 201, response.text
    return response.json()


def search(s, preview_id=None, mode="demo"):
    return s.matching.client.post(
        "/v1/matches",
        json={
            "organization_id": s.organization_id,
            "need_id": s.need["need_id"],
            "ranking_policy": "governed-v1",
            "policy_id": s.policy,
            "mode": mode,
            "intent_preview_id": preview_id,
        },
        headers=headers(s.employer_auth, "governed-search" + str(uuid4())),
    )


def test_reviewed_semantics_maps_all_evidence_and_revocation_closes_snapshot(setup):
    s = setup
    create_versions(s)
    assert search(s).status_code == 409
    approve_policy(s)
    p = preview(s)
    assert p["proposal"]["desired"] == ["postgresql"]
    assert p["proposal"]["grade"] is None
    assert search(s, p["preview_id"]).status_code == 404
    reviewed = {
        "specialization": "backend",
        "grade": "middle",
        "mandatory": ["postgresql"],
        "desired": [],
        "unknowns": [],
    }
    confirmed = s.matching.client.post(
        f"/v1/matches/intent-previews/{p['preview_id']}/confirmation",
        json=reviewed,
        headers=headers(s.employer_auth, "confirm"),
    )
    assert confirmed.status_code == 200, confirmed.text
    # Confirmed intent replaces the existing python requirement with PostgreSQL.
    inject(s, evidence(scores={"python": 90, "sql": 85, "query-planning": 20}))
    refresh(s)
    assert search(s, p["preview_id"]).json()["matches"] == []
    inject(s, evidence(scores={"python": 90, "sql": 85, "query-planning": 90}), revision=1)
    refresh(s)
    result = search(s, p["preview_id"])
    assert result.status_code == 201, result.text
    item = result.json()["matches"][0]
    assert item["score_components"]["competency"] == 85
    assert item["policy_version"] == "test-policy-v1"
    assert item["catalog_id"] == s.catalog
    assert item["calibrated"] is False
    # A candidate selected by the reviewed requirement can enter the existing Hiring flow.
    from tests.integration.test_matching_hiring import consent, invite

    invitation = invite(s, "governed-match-invite")
    assert invitation.status_code == 201, invitation.text
    invitation_id = invitation.json()["invitation_id"]
    assert invitation.json()["candidate_id"] == item["candidate_id"]
    disclosure = consent(s, "contact_disclosure")
    accepted = s.hiring.client.post(
        f"/v1/invitations/{invitation_id}/accept",
        json={"disclosure_consent_id": disclosure},
        headers=headers(s.auth, "governed-match-accept", 1),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["status"] == "accepted"
    # The search refinement must not overwrite the Hiring-owned Need.
    unchanged = s.matching.app.state.market_access.require(
        "hiring",
        "need",
        candidate_id=s.recruiter_id,
        actor_id=s.recruiter_id,
        organization_id=UUID(s.organization_id),
        need_id=UUID(s.need["need_id"]),
    )
    assert unchanged.data["required_skills"] == ["python"]
    revoked = s.matching.client.post(
        f"/v1/matches/governance/versions/{s.policy}/decisions",
        json={
            "expected_revision": 2,
            "decision": "revoked",
            "reason": "New policy version required",
        },
        headers=headers(s.reviewer, "revoke"),
    )
    assert revoked.status_code == 200
    assert (
        s.matching.client.get(
            f"/v1/matches/{result.json()['snapshot_id']}", headers=headers(s.employer_auth)
        ).status_code
        == 409
    )


def test_llm_requires_source_quotes_and_explicit_unknowns_and_confirmation(setup):
    s = setup
    create_versions(s)
    approve_policy(s)
    body = {
        "organization_id": s.organization_id,
        "need_id": s.need["need_id"],
        "catalog_id": s.catalog,
        "text": "backend middle python",
        "parser": "llm",
    }
    assert (
        s.matching.client.post(
            "/v1/matches/intent-previews",
            json=body,
            headers=headers(s.employer_auth, "unconfigured"),
        ).status_code
        == 503
    )
    s.matching.app.state.matching_intent_gateway = SimpleNamespace(
        parse=lambda inputs, **kw: ParsedIntent(
            specialization="backend",
            grade="senior",
            mandatory=["python"],
            citations={
                "specialization": "backend",
                "grade": "fabricated",
                "mandatory:python": "python",
            },
        )
    )
    assert (
        s.matching.client.post(
            "/v1/matches/intent-previews",
            json=body,
            headers=headers(s.employer_auth, "unsupported"),
        ).status_code
        == 422
    )
    s.matching.app.state.matching_intent_gateway = SimpleNamespace(
        parse=lambda inputs, **kw: ParsedIntent(
            specialization="backend",
            mandatory=["python"],
            citations={"specialization": "backend", "mandatory:python": "python"},
        )
    )
    p = preview(s, parser="llm", text=body["text"])
    assert p["proposal"]["grade"] is None and "grade" in p["proposal"]["unknowns"]
    endpoint = f"/v1/matches/intent-previews/{p['preview_id']}/confirmation"
    assert (
        s.matching.client.post(
            endpoint, json=p["proposal"], headers=headers(s.employer_auth, "incomplete")
        ).status_code
        == 422
    )
    with Session(s.matching.app.state.engine) as session, session.begin():
        session.get(IntentPreview, p["preview_id"]).expires_at = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    confirmed = {**p["proposal"], "grade": "middle", "unknowns": []}
    assert (
        s.matching.client.post(
            endpoint, json=confirmed, headers=headers(s.employer_auth, "expired")
        ).status_code
        == 409
    )


def test_production_policy_registers_criterion_before_import_and_no_demo_evidence(setup):
    s = setup
    create_versions(s, demo=False)
    decision = {
        "expected_revision": 1,
        "decision": "approved",
        "reason": "Independent calibration review",
    }
    assert (
        s.matching.client.post(
            f"/v1/matches/governance/versions/{s.policy}/decisions",
            json=decision,
            headers=headers(s.reviewer, "before-calibration"),
        ).status_code
        == 409
    )
    endpoint = f"/v1/matches/governance/policies/{s.policy}/calibration"
    report = {
        "dataset_digest": "a" * 64,
        "report_digest": "b" * 64,
        "labeled_pairs": 100,
        "precision_at_k": 0.9,
        "minimum_precision": 0.7,
        "k": 10,
    }
    assert (
        s.matching.client.post(
            endpoint,
            json={"expected_revision": 1, "report": report},
            headers=headers(s.admin, "wrong-threshold"),
        ).status_code
        == 422
    )
    report["minimum_precision"] = 0.8
    result = s.matching.client.post(
        endpoint,
        json={"expected_revision": 1, "report": report},
        headers=headers(s.admin, "import"),
    )
    assert result.status_code == 200, result.text
    assert (
        s.matching.client.post(
            endpoint,
            json={"expected_revision": 2, "report": report},
            headers=headers(s.admin, "reimport"),
        ).status_code
        == 409
    )
    approve_policy(s, {**decision, "expected_revision": 2})
    inject(s, evidence())
    refresh(s)
    result = search(s, mode="production")
    assert result.status_code == 201, result.text
    assert result.json()["matches"] == []  # Every current CandidateCard is explicitly synthetic.


def test_advice_policy_changes_freshness_and_recommendation_without_changing_grade():
    now = datetime.now(UTC)
    policy = RankingPolicy(
        version="advice-v2", catalog_id=uuid4(), current_days=5, expiry_days=10, next_grade_score=99
    )
    proof = evidence(age=8)
    summary = SimpleNamespace(
        qualification=proof, status="confirmed", target_grade="middle", specialization="backend"
    )
    result = advice(uuid4(), summary, "middle", now=now, policy=policy)
    assert result.policy_version == "advice-v2"
    assert result.freshness == "aging"
    assert result.recommended_next_grade is None
    assert freshness(proof.assessed_at, now, policy=policy) == ("aging", 50)
    with pytest.raises(ValidationError):
        RankingPolicy(version="bad", catalog_id=uuid4(), calibration_minimum_precision=0)


def test_unknown_catalog_mapping_and_ambiguous_alias_fail_closed():
    with pytest.raises(ValidationError):
        Vocabulary(
            version="bad",
            specializations=["backend"],
            entries=[
                {"key": "python", "aliases": ["postgres"], "evidence_keys": ["python"]},
                {"key": "postgres", "evidence_keys": ["sql"]},
            ],
        )
    catalog = Vocabulary(
        version="v1",
        specializations=["backend"],
        entries=[{"key": "python", "evidence_keys": ["python"]}],
    )
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        validate_intent(ParsedIntent(mandatory=["unknown"]), catalog)


def test_signed_advice_policy_fresh_binding_replay_and_revocation(setup):
    from reverse_hr.protocols.qualification_policy_access import (
        REQUEST_CONTEXT,
        PolicyRequest,
        QualificationPolicyAccess,
    )
    from reverse_hr.shared.signing import canonical, sign

    s = setup
    create_versions(s)
    approve_policy(s)
    inject(s, evidence(age=45))
    access = QualificationPolicyAccess(s.candidate.app.state.settings)
    access._signatures, access._send = s.signatures["candidate"], s.sender
    s.candidate.app.state.qualification_policy_access = access
    result = s.candidate.client.get(
        "/v1/candidates/me/qualification", params={"policy_id": s.policy}, headers=headers(s.auth)
    )
    assert result.status_code == 200, result.text
    item = result.json()[0]
    assert item["policy_version"] == "test-policy-v1" and item["freshness"] == "aging"
    request = PolicyRequest(
        policy_id=s.policy,
        candidate_id=s.candidate_id,
        mode="demo",
        issued_at=datetime.now(UTC),
        nonce=uuid4(),
    )
    signed = {
        "Content-Type": "application/json",
        "X-HR-Signature": sign(s.signatures["candidate"], REQUEST_CONTEXT, request),
    }
    endpoint = "/internal/v1/qualification-policy"
    assert (
        s.matching.client.post(endpoint, content=canonical(request), headers=signed).status_code
        == 200
    )
    assert (
        s.matching.client.post(endpoint, content=canonical(request), headers=signed).status_code
        == 409
    )
    stale = request.model_copy(
        update={"issued_at": datetime.now(UTC) - timedelta(seconds=40), "nonce": uuid4()}
    )
    assert (
        s.matching.client.post(
            endpoint,
            content=canonical(stale),
            headers={
                **signed,
                "X-HR-Signature": sign(s.signatures["candidate"], REQUEST_CONTEXT, stale),
            },
        ).status_code
        == 401
    )
    revoked = s.matching.client.post(
        f"/v1/matches/governance/versions/{s.policy}/decisions",
        json={
            "expected_revision": 2,
            "decision": "revoked",
            "reason": "Calibration update pending",
        },
        headers=headers(s.reviewer, "revoke-advice"),
    )
    assert revoked.status_code == 200
    assert (
        s.candidate.client.get(
            "/v1/candidates/me/qualification",
            params={"policy_id": s.policy},
            headers=headers(s.auth),
        ).status_code
        == 409
    )


def test_confirmation_replay_conditions_and_privacy_erase_do_not_resurrect(setup):
    from reverse_hr.services.matching.domain.matching import process_deletion_request
    from tests.services.code_runner.test_code_runner import deletion

    s = setup
    create_versions(s)
    approve_policy(s)
    p = preview(s)
    endpoint = f"/v1/matches/intent-previews/{p['preview_id']}/confirmation"
    body = {
        "specialization": "backend",
        "grade": "middle",
        "mandatory": ["python"],
        "conditions": ["Salary must be confirmed by recruiter"],
    }
    response = s.matching.client.post(
        endpoint, json=body, headers=headers(s.employer_auth, "repeat-confirm")
    )
    assert response.status_code == 200
    replay = s.matching.client.post(
        endpoint, json=body, headers=headers(s.employer_auth, "repeat-confirm")
    )
    assert replay.status_code == 200 and replay.json() == response.json()
    assert search(s, p["preview_id"]).status_code == 409
    with Session(s.matching.app.state.engine) as session, session.begin():
        event = deletion(s.recruiter_id)
        process_deletion_request(session, event)
    with Session(s.matching.app.state.engine) as session:
        assert session.get(IntentPreview, p["preview_id"]) is None
    assert (
        s.matching.client.post(
            endpoint, json=body, headers=headers(s.employer_auth, "repeat-confirm")
        ).status_code
        == 409
    )


def test_policy_author_privacy_restriction_rejects_fresh_find(setup):

    s = setup
    create_versions(s)
    approve_policy(s)
    with Session(s.matching.app.state.engine) as session:
        policy = session.get(GovernanceVersion, s.policy)
        author = UUID(policy.author_id)
    # Current processing permission, not the historical approval, controls access.
    from fastapi import HTTPException

    original = s.matching.app.state.processing_access.check

    def checked(subject):
        if subject == author:
            raise HTTPException(409)
        return original(subject)

    s.matching.app.state.processing_access.check = checked
    assert search(s).status_code == 409
