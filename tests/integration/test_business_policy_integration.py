"""Candidate advice uses fresh, signed, independently approved Matching policies."""

from uuid import uuid4

from reverse_hr.protocols.qualification_policy_access import QualificationPolicyAccess
from tests.integration.test_matching_hiring import setup as matching_fixture
from tests.services.matching.test_matching_governance import approve_policy, create_versions
from tests.services.matching.test_matching_qualification import evidence, inject
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture
setup = matching_fixture


def wire(s):
    access = QualificationPolicyAccess(s.candidate.app.state.settings)
    access._signatures = s.signatures["candidate"]
    access._send = s.sender
    s.candidate.app.state.qualification_policy_access = access
    return access


def test_candidate_consumes_signed_policy_and_revocation_closes_access(setup):
    s = setup
    create_versions(s)
    approve_policy(s)
    assert s.matching.client.post("/internal/v1/qualification-policy", json={}).status_code == 401
    inject(s, evidence(age=40))
    wire(s)
    path = "/v1/candidates/me/qualification"
    ordinary = s.candidate.client.get(path, headers=headers(s.auth))
    assert ordinary.status_code == 200, ordinary.text
    assert ordinary.json()[0]["freshness"] == "current"
    governed = s.candidate.client.get(path, params={"policy_id": s.policy}, headers=headers(s.auth))
    assert governed.status_code == 200, governed.text
    item = governed.json()[0]
    assert item["freshness"] == "aging"
    assert item["policy_version"] == "test-policy-v1"
    assert item["demo"] and not item["calibrated"]
    assert item["next_attempt_at"] == ordinary.json()[0]["next_attempt_at"]
    result = s.matching.client.post(
        f"/v1/matches/governance/versions/{s.policy}/decisions",
        json={
            "expected_revision": 2,
            "decision": "revoked",
            "reason": "Withdraw current recommendation policy",
        },
        headers=headers(s.reviewer, "root-revoke"),
    )
    assert result.status_code == 200, result.text
    assert (
        s.candidate.client.get(
            path, params={"policy_id": s.policy}, headers=headers(s.auth)
        ).status_code
        == 409
    )


def test_revocation_during_candidate_report_cannot_serve_old_policy(setup):
    s = setup
    create_versions(s)
    approve_policy(s)
    inject(s, evidence(age=40))
    access = wire(s)
    original = access.fetch
    calls = []

    def fetch(*args):
        policy = original(*args)
        calls.append(True)
        if len(calls) == 1:
            result = s.matching.client.post(
                f"/v1/matches/governance/versions/{s.policy}/decisions",
                json={
                    "expected_revision": 2,
                    "decision": "revoked",
                    "reason": "Concurrent policy revocation",
                },
                headers=headers(s.reviewer, str(uuid4())),
            )
            assert result.status_code == 200, result.text
        return policy

    access.fetch = fetch
    result = s.candidate.client.get(
        "/v1/candidates/me/qualification", params={"policy_id": s.policy}, headers=headers(s.auth)
    )
    assert result.status_code == 409, result.text


def test_production_advice_requires_production_policy_and_proof(setup):
    s = setup
    inject(s, evidence())
    result = s.candidate.client.get(
        "/v1/candidates/me/qualification",
        params={"policy_mode": "production"},
        headers=headers(s.auth),
    )
    assert result.status_code == 409
    s.candidate.app.state.settings.deployment_mode = "production"
    result = s.candidate.client.get("/v1/candidates/me/qualification", headers=headers(s.auth))
    assert result.status_code == 409


def test_approved_production_policy_cannot_relabel_demo_assessment():
    from datetime import UTC, datetime
    from types import SimpleNamespace

    from reverse_hr.contracts.core import Grade
    from reverse_hr.contracts.qualification import advice

    summary = SimpleNamespace(
        qualification=evidence(),
        status="confirmed",
        specialization="backend",
        target_grade=Grade.middle,
    )
    policy = SimpleNamespace(
        demo=False,
        current_days=30,
        expiry_days=90,
        advice_target=70,
        next_grade_score=90,
        next_grade_competency=80,
        version="approved-production-v1",
    )
    result = advice(uuid4(), summary, Grade.middle, now=datetime.now(UTC), policy=policy)
    assert result.demo is True
    assert result.calibrated is False
    assert result.policy_version == "approved-production-v1"
