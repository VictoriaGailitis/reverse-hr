"""Independent grades and live consent-gated cards for concurrent specializations."""

from uuid import uuid4

from tests.integration.test_matching_hiring import grade, matches, refresh
from tests.integration.test_matching_hiring import setup as setup
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures


def save(s, additional):
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    reply = s.candidate.client.put(
        "/v1/candidates/me",
        json=dict(
            display_name="Candidate",
            specialization="backend",
            declared_grade="lead",
            additional_specializations=additional,
        ),
        headers=headers(s.auth, str(uuid4()), profile["version"]),
    )
    return reply


def test_multiple_grades_matching_removal_and_signed_selection(setup):
    s = setup
    response = save(s, [dict(specialization="security", declared_grade="senior")])
    assert response.status_code == 200, response.text
    assert response.json()["specializations"][1]["confirmed_grade"] is None
    before = response.json()["version"]
    grade(s, "junior", "security")
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    assert profile["version"] == before + 1
    assert profile["confirmed_grade"] == "middle"
    assert profile["specializations"][1]["confirmed_grade"] == "junior"
    access = s.matching.app.state.market_access
    card = access.fetch(
        "candidate", "profile", candidate_id=s.candidate_id, specialization="security"
    )
    assert card.allowed and card.data["confirmed_grade"] == "junior"
    assert not access.fetch(
        "candidate", "profile", candidate_id=s.candidate_id, specialization="unknown"
    ).allowed
    need = s.hiring.client.post(
        "/v1/hiring-needs",
        json=dict(
            organization_id=s.organization_id,
            specialization="security",
            confirmed_grade="junior",
            required_skills=["python"],
            status="published",
        ),
        headers=headers(s.employer_auth, "security-need"),
    )
    assert need.status_code == 201, need.text
    s.need = need.json()
    refresh(s)
    result = matches(s)
    assert result.status_code == 201, result.text
    assert result.json()["matches"][0]["specialization"] == "security"
    snapshot = result.json()["snapshot_id"]
    assert save(s, []).status_code == 200
    assert (
        s.matching.client.get("/v1/matches/" + snapshot, headers=s.employer_auth).json()["matches"]
        == []
    )
    assert not access.fetch(
        "candidate", "profile", candidate_id=s.candidate_id, specialization="security"
    ).allowed
    # Reactivating a direction restores its own retained evidence, never another direction's grade.
    response = save(s, [dict(specialization="security", declared_grade="lead")])
    assert response.json()["specializations"][1]["confirmed_grade"] == "junior"


def test_duplicate_and_excess_specializations_rejected(setup):
    s = setup
    assert save(s, [dict(specialization=" Backend ", declared_grade="junior")]).status_code == 422
    assert save(s, [dict(specialization=" ", declared_grade="junior")]).status_code == 422
    assert (
        save(
            s, [dict(specialization=f"track-{i}", declared_grade="junior") for i in range(10)]
        ).status_code
        == 422
    )
