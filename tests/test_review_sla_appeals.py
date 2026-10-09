"""Real appeal assignments across independently migrated service databases."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy.orm import Session
from test_access import headers
from test_assessment_appeals import rereview, resolve, submit
from test_assessment_appeals import setup as appeal_setup
from test_employer_trust import path, sanction
from test_event_transport import signatures as signatures_fixture
from test_matching_hiring import setup as market_setup

from reverse_hr.domains.assessment_appeals import Appeal
from reverse_hr.domains.employer_trust import TrustAppeal
from reverse_hr.review_sla import run_one

signatures = signatures_fixture
setup = market_setup
assessment_setup = appeal_setup


def test_assessment_worker_assigns_independent_peer_and_resolves(assessment_setup):
    s = assessment_setup
    row = submit(s).json()
    now = datetime.now(UTC)
    with Session(s.assessment.app.state.engine) as session, session.begin():
        session.get(Appeal, row["appeal_id"]).review_due_at = now - timedelta(minutes=1)
    registered = s.assessment.client.put("/v1/review-sla/availability", headers=s.peer)
    assert registered.status_code == 200, registered.text
    request = SimpleNamespace(app=s.assessment.app, state=SimpleNamespace(trace_id=uuid4()))
    assert run_one(request, now=now)
    assert not run_one(request, now=now)
    result = s.assessment.client.get("/v1/assessment-appeals/" + row["appeal_id"], headers=s.peer)
    assert result.status_code == 200, result.text
    assigned = result.json()
    assert assigned["reviewer_id"] == str(s.peer_id)
    assert assigned["status"] == "in_review"
    assert assigned["version"] == 2
    assert rereview(s).status_code == 200
    decision = resolve(s, assigned)
    assert decision.status_code == 200, decision.text
    assert not run_one(request, now=now + timedelta(days=30))


def test_employer_worker_excludes_original_moderator_and_updates_real_appeal(setup):
    s = setup
    target = sanction(s)
    assert target.status_code == 201, target.text
    result = s.employer.client.post(
        path(s) + "/trust-appeals/" + target.json()["sanction_id"],
        json={"reason": "Independent review requested"},
        headers=headers(s.employer_auth, "appeal"),
    )
    assert result.status_code == 201, result.text
    row = result.json()
    now = datetime.now(UTC)
    with Session(s.employer.app.state.engine) as session, session.begin():
        appeal = session.get(TrustAppeal, row["appeal_id"])
        appeal.data = appeal.data | {"due_at": (now - timedelta(days=3)).isoformat()}
    original = s.employer.client.put("/v1/review-sla/availability", headers=s.moderator)
    assert original.status_code == 200
    peer_id = uuid4()
    peer = s.token(peer_id, ("company_moderator",), amr=["mfa"])
    assert s.employer.client.put("/v1/review-sla/availability", headers=peer).status_code == 200
    request = SimpleNamespace(app=s.employer.app, state=SimpleNamespace(trace_id=uuid4()))
    assert run_one(request, now=now)
    assert not run_one(request, now=now)
    with Session(s.employer.app.state.engine) as session:
        appeal = session.get(TrustAppeal, row["appeal_id"])
        assert appeal.reviewer_id == str(peer_id)
        assert appeal.version == 2
    decided = s.employer.client.post(
        path(s) + "/trust-appeals/" + row["appeal_id"] + "/decision",
        json={"outcome": "upheld", "reason": "Original sanction justified"},
        headers=headers(peer, "sla-decision", 2),
    )
    assert decided.status_code == 200, decided.text
    assert not run_one(request, now=now + timedelta(days=30))
