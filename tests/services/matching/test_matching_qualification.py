"""Signed Candidate publication → verified Matching, without treating declarations as proof."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.market_contracts import CandidateCard, NeedView
from reverse_hr.contracts.qualification import advice
from reverse_hr.contracts.qualification_contracts import QualificationEvidence
from reverse_hr.protocols.confirmed_grade_access import DecisionSummary
from reverse_hr.services.candidate.domain.candidate_grades import (
    CandidateDecision,
    process_grade_decision,
)
from reverse_hr.services.matching.domain.matching import MatchQuery, verified_rank
from reverse_hr.shared.db import Outbox
from tests.integration.test_matching_hiring import publication
from tests.integration.test_matching_hiring import refresh as original_refresh
from tests.integration.test_matching_hiring import setup as matching_fixture
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture
setup = matching_fixture


def refresh(s):
    with Session(s.candidate.app.state.engine) as session:
        events = [
            EventEnvelope.model_validate(row.envelope)
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "candidate.profile_updated.v1"
            and row.envelope["payload"]["candidate_id"] == str(s.candidate_id)
        ]
        event = max(events, key=lambda item: item.aggregate_version)
    return original_refresh(s, event)


def evidence(age=0, scores=None, overall=92, cooldown=0):
    now = datetime.now(UTC)
    return QualificationEvidence(
        policy_id=uuid4(),
        evidence_digest="a" * 64,
        assessed_at=now - timedelta(days=age),
        score=overall,
        competency_scores=scores or {"python": 90},
        competency_minimums={"python": 60},
        next_attempt_at=now + timedelta(seconds=cooldown),
        grade_change_available_at=now + timedelta(seconds=cooldown),
    )


def inject(s, proof, level="senior", revision=1, supersedes=None, sid=None):
    sid = sid or uuid4()
    summary = DecisionSummary(
        specialization="backend",
        target_grade=level,
        status="confirmed",
        decided_at=datetime.now(UTC),
        qualification=proof,
        decision_revision=revision,
        supersedes_decision_id=supersedes,
    )
    event = EventEnvelope(
        producer="assessment",
        event_type="assessment.grade_decision_recorded.v1",
        aggregate_id=sid,
        aggregate_version=5 + revision,
        correlation_id=uuid4(),
        payload={
            "candidate_id": s.candidate_id,
            "session_id": sid,
            "decision_id": uuid4(),
            "reviewer_id": uuid4(),
        },
    )
    access = SimpleNamespace(fetch=lambda **_: summary, check=lambda *_: None)
    with Session(s.candidate.app.state.engine) as session, session.begin():
        process_grade_decision(session, event, access)
    refresh(s)
    return event, summary, access


def find(s, **extra):
    return s.matching.client.post(
        "/v1/matches",
        json={
            "organization_id": s.organization_id,
            "need_id": s.need["need_id"],
            "mode": "demo",
            "ranking_policy": "verified-demo-v1",
            **extra,
        },
        headers=headers(s.employer_auth, str(uuid4())),
    )


def test_verified_matching_requires_actual_signed_competency_evidence(setup):
    s = setup
    assert find(s).json()["matches"] == []  # declared python is not proof
    inject(s, evidence(scores={"python": 50}))
    assert find(s).json()["matches"] == []
    event, _, _ = inject(s, evidence(scores={"python": 90}), "lead")
    response = find(s, desired_competencies=["sql"])
    assert response.status_code == 201, response.text
    card = response.json()["matches"][0]
    assert card["decision_id"] == str(event.payload["decision_id"])
    assert card["score_components"]["competency"] == 45
    assert card["score"] == 62  # 55*.45 + 25*.92 + 15*1, floored
    assert not card["calibrated"] and card["evaluated_on"]
    assert "Declared skills do not" in card["explanation"]
    assert find(s, mode="production").status_code == 409
    snapshot = response.json()["snapshot_id"]
    assert publication(s, False).status_code == 200
    assert (
        s.matching.client.get(f"/v1/matches/{snapshot}", headers=s.employer_auth).json()["matches"]
        == []
    )


def test_expiration_and_grade_do_not_implicitly_downgrade(setup):
    s = setup
    inject(s, evidence(age=366))
    assert find(s).json()["matches"] == []
    result = s.candidate.client.get("/v1/candidates/me/qualification", headers=s.auth)
    assert result.status_code == 200, result.text
    report = result.json()[0]
    assert report["freshness"] == "expired" and report["repeat_recommended"]
    assert report["current_grade"] == "senior" and not report["recommended_next_grade"]


def test_advice_respects_cooldowns_and_does_not_assign_grade():
    summary = DecisionSummary(
        specialization="backend",
        target_grade="middle",
        status="confirmed",
        decided_at=datetime.now(UTC),
        qualification=evidence(cooldown=60),
    )
    report = advice(uuid4(), summary, "middle")
    assert not report.retry_available and report.recommended_next_grade is None
    report = advice(uuid4(), summary, "middle", datetime.now(UTC) + timedelta(minutes=2))
    assert report.recommended_next_grade == "senior" and report.current_grade == "middle"
    weak = summary.model_copy(update={"qualification": evidence(scores={"python": 45})})
    assert "45/100" in advice(uuid4(), weak, "middle").feedback[0]


def test_appeal_supersession_changes_evidence_and_replay_is_immutable(setup):
    s = setup
    old, summary, access = inject(s, evidence())
    saved = find(s).json()
    inject(
        s,
        evidence(scores={"python": 50}),
        "senior",
        2,
        old.payload["decision_id"],
        old.aggregate_id,
    )
    # Replay of old signed decision does not restore superseded proof or conflict.
    with Session(s.candidate.app.state.engine) as session, session.begin():
        assert process_grade_decision(session, old, access) is False
        row = session.get(CandidateDecision, str(old.payload["decision_id"]))
        assert row.summary == summary.model_dump(mode="json")
    assert find(s).json()["matches"] == []
    assert (
        s.matching.client.get(
            f"/v1/matches/{saved['snapshot_id']}", headers=s.employer_auth
        ).json()["matches"]
        == []
    )


def test_preview_confirmation_refinement_and_comparison_privacy(setup):
    s = setup
    inject(s, evidence())
    preview = s.matching.client.post(
        "/v1/matches/query-preview",
        json={
            "organization_id": s.organization_id,
            "need_id": s.need["need_id"],
            "text": "Python, strong system design, salary 999999",
        },
        headers=s.employer_auth,
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["requires_employer_confirmation"]
    assert preview.json()["proposed_query"]["desired_competencies"] == ["python"]
    saved = find(s).json()
    refinement = s.matching.client.post(
        f"/v1/matches/{saved['snapshot_id']}/refinements",
        json=preview.json()["proposed_query"] | {"desired_competencies": ["sql"]},
        headers=headers(s.employer_auth, "refine"),
    )
    assert refinement.status_code == 201, refinement.text
    assert refinement.json()["snapshot_id"] != saved["snapshot_id"]
    comparison = s.matching.client.post(
        f"/v1/matches/{saved['snapshot_id']}/comparison",
        json={"candidate_ids": [str(s.candidate_id), str(uuid4())]},
        headers=s.employer_auth,
    )
    assert comparison.status_code == 404  # never disclose arbitrary profile IDs
    denied = s.matching.client.post(
        f"/v1/matches/{saved['snapshot_id']}/refinements",
        json=preview.json()["proposed_query"],
        headers=headers(s.token(uuid4(), ("employer",)), "other-refine"),
    )
    assert denied.status_code == 404


@pytest.mark.parametrize("age,expected", [(1, 100), (181, 50), (366, 0)])
def test_deterministic_freshness_components(age, expected):
    proof = evidence(age=age)
    card = CandidateCard(
        candidate_id=uuid4(),
        display_name="Synthetic",
        specialization="backend",
        confirmed_grade="middle",
        decision_id=uuid4(),
        version=1,
        declared_skills=["sql"],
        qualification=proof,
    )
    need = NeedView(
        organization_id=uuid4(),
        need_id=uuid4(),
        created_by=uuid4(),
        version=1,
        specialization="backend",
        confirmed_grade="junior",
        required_skills=["python"],
        status="published",
    )
    query = MatchQuery(
        organization_id=need.organization_id,
        need_id=need.need_id,
        mode="demo",
        ranking_policy="verified-demo-v1",
        maximum_evidence_age_days=1000,
    )
    ranked = verified_rank(card, need, query)
    assert ranked["score_components"]["freshness"] == expected
    assert ranked == verified_rank(card, need, query)
    assert UUID(ranked["decision_id"]) == card.decision_id


def test_same_grade_retest_refreshes_reviewed_evidence_without_grade_change(setup):
    s = setup
    old, _, _ = inject(s, evidence(age=200))
    first = find(s).json()["matches"][0]
    newer, _, _ = inject(s, evidence(age=0))
    updated = find(s).json()["matches"][0]
    assert first["decision_id"] == str(old.payload["decision_id"])
    assert updated["decision_id"] == str(newer.payload["decision_id"])
    assert updated["confirmed_grade"] == first["confirmed_grade"] == "senior"
    assert updated["score_components"]["freshness"] > first["score_components"]["freshness"]


def test_comparison_contains_only_live_published_candidates(setup):
    from tests.integration.test_matching_hiring import consent

    s = setup
    inject(s, evidence())
    second = SimpleNamespace(**vars(s))
    second.candidate_id = uuid4()
    second.auth = s.token(second.candidate_id)
    response = s.candidate.client.post(
        "/v1/candidates/me",
        json={
            "display_name": "Second synthetic",
            "specialization": "backend",
            "declared_grade": "lead",
        },
        headers=headers(second.auth, "second-profile"),
    )
    assert response.status_code == 201
    second.consent = consent(second, "profile_publication")
    inject(second, evidence(overall=75))
    assert publication(second, True).status_code == 200
    refresh(second)
    saved = find(s).json()
    assert len(saved["matches"]) == 2
    body = {"candidate_ids": [str(s.candidate_id), str(second.candidate_id)]}
    response = s.matching.client.post(
        f"/v1/matches/{saved['snapshot_id']}/comparison", json=body, headers=s.employer_auth
    )
    assert response.status_code == 200, response.text
    assert len(response.json()["matches"]) == 2
    assert all(
        not {"email", "phone", "reason", "reviewer_id"} & item.keys()
        for item in response.json()["matches"]
    )
    assert publication(second, False).status_code == 200
    response = s.matching.client.post(
        f"/v1/matches/{saved['snapshot_id']}/comparison", json=body, headers=s.employer_auth
    )
    assert response.status_code == 404
