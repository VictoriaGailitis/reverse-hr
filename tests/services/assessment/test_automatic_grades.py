"""Real signed score flow with synthetic expert labels; no production calibration claim."""

from types import SimpleNamespace
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.test_suites import digest
from reverse_hr.services.assessment.domain.assessment_automatic import AutomaticReview, run_one
from reverse_hr.services.assessment.domain.assessment_grades import (
    GradeDecision,
    GradePolicy,
    Rules,
    policy_digest,
)
from reverse_hr.services.assessment.domain.assessment_sessions import PracticalSession
from reverse_hr.services.evaluation.domain.evaluation_review import ReviewRecord
from reverse_hr.services.evaluation.evaluation_automatic import run_one as stage_one
from tests.services.assessment.test_assessment_grades import proposal
from tests.services.assessment.test_assessment_grades import setup as setup
from tests.services.assessment.test_assessment_grades import signatures as signatures
from tests.services.code_runner.test_submitted_tests import tick
from tests.shared.test_access import headers


def automatic_policy(s, **changes):
    with Session(s.assessment.app.state.engine) as db, db.begin():
        p = db.get(GradePolicy, s.policy_id)
        p.rules = Rules.model_validate(
            p.rules | {"automatic_decisions": True, "audit_percent": 0} | changes
        ).model_dump(mode="json")
        p.rules_digest = digest(Rules.model_validate(p.rules))
        db.get(PracticalSession, str(s.session_id)).grade_policy_digest = policy_digest(p)


def stage(s):
    target = s.evaluation.app.state
    return stage_one(
        target.engine,
        target.settings,
        target.material_access,
        target.artifact_access,
        target.processing_access,
        s.signatures["evaluation"],
    )


def request(s):
    return SimpleNamespace(app=s.assessment.app, state=SimpleNamespace(trace_id=uuid4()))


def test_automatic_signed_test_score_and_grade_are_idempotent(setup):
    s = setup
    automatic_policy(s)
    assert stage(s)  # Waiting for pinned tests must not fail the stage.
    assert proposal(s)["score"] is None
    for _ in range(len(s.definition.cases) + 2):
        assert tick(s)
    assert stage(s)
    assert not stage(s)
    assert run_one(request(s))
    assert not run_one(request(s))
    result = proposal(s)
    assert result["score"] == 100 and result["origin"] == "automatic"
    assert result["confirmed_grade"] == "junior" and not result["review_required"]
    with Session(s.evaluation.app.state.engine) as db:
        assert len(list(db.scalars(select(ReviewRecord)))) == 1
        assert db.scalar(select(ReviewRecord)).origin == "automatic"
    with Session(s.assessment.app.state.engine) as db:
        assert len(list(db.scalars(select(GradeDecision)))) == 1


def test_boundary_waits_for_human_without_publishing_grade(setup):
    s = setup
    automatic_policy(s, pass_score=98)
    for _ in range(len(s.definition.cases) + 2):
        assert tick(s)
    assert stage(s) and run_one(request(s))
    with Session(s.assessment.app.state.engine) as db:
        assert db.scalar(select(GradeDecision)) is None
        assert db.get(AutomaticReview, str(s.session_id)).reasons == ["grade_boundary"]
    assert proposal(s)["review_required"]


def test_sample_publishes_grade_and_opens_independent_recheck(setup):
    s = setup
    automatic_policy(s, audit_percent=100)
    for _ in range(len(s.definition.cases) + 2):
        assert tick(s)
    assert stage(s) and run_one(request(s))
    assert proposal(s)["confirmed_grade"] == "junior"
    assert proposal(s)["review_required"]
    path = f"/v1/assessment-automatic/{s.session_id}/recheck"
    result = s.assessment.client.post(path, json={}, headers=headers(s.grade_auth, "recheck"))
    assert result.status_code == 200, result.text
    assert (
        s.assessment.client.post(path, json={}, headers=headers(s.grade_auth, "recheck")).json()
        == result.json()
    )
    candidate = s.assessment.client.post(
        path, json={}, headers=headers(s.auth, "candidate-recheck")
    )
    assert candidate.status_code == 403


def test_open_quality_case_accepts_candidate_objection_once(setup):
    s = setup
    automatic_policy(s, audit_percent=100)
    for _ in range(len(s.definition.cases) + 2):
        assert tick(s)
    assert stage(s) and run_one(request(s))
    decision = proposal(s)["decision_id"]
    reply = s.assessment.client.post(
        f"/v1/assessment-automatic/{s.session_id}/recheck",
        json={},
        headers=headers(s.grade_auth, "quality-case"),
    )
    assert reply.status_code == 200, reply.text
    body = dict(
        decision_id=decision, reason="Please independently check the explanation of this result"
    )
    reply = s.assessment.client.post(
        "/v1/assessment-appeals", json=body, headers=headers(s.auth, "candidate-quality-objection")
    )
    assert reply.status_code == 201, reply.text
    assert reply.json()["reason"] == body["reason"]
    assert (
        s.assessment.client.post(
            "/v1/assessment-appeals",
            json=body,
            headers=headers(s.auth, "candidate-quality-duplicate"),
        ).status_code
        == 409
    )


def test_open_risk_blocks_automatic_grade_even_after_completed_stage_review(setup):
    from reverse_hr.services.evaluation.domain.evaluation import EvaluationIntake
    from reverse_hr.services.evaluation.evaluation_risk import register

    s = setup
    automatic_policy(s)
    for _ in range(len(s.definition.cases) + 2):
        assert tick(s)
    assert stage(s)
    with Session(s.evaluation.app.state.engine) as db, db.begin():
        intake = db.scalar(select(EvaluationIntake))
        assert intake.score == 100
        register(db, intake, ["instruction_override"])
    assert run_one(request(s))
    with Session(s.assessment.app.state.engine) as db:
        assert db.scalar(select(GradeDecision)) is None
        assert db.get(AutomaticReview, str(s.session_id)).reasons == [
            "additional_verification_required"
        ]
