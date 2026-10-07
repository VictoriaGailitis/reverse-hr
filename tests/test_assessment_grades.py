"""Synthetic calibration only; signed stage exports and actual human command paths."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture
from test_submitted_tests import setup as runner_setup
from test_submitted_tests import tick

from reverse_hr.domains.assessment_grades import (
    CandidateGrade,
    GradeDecision,
    GradePolicy,
    policy_digest,
)
from reverse_hr.domains.assessment_sessions import PracticalSession, process_deletion_request
from reverse_hr.evaluation_artifact_access import ArtifactAccess
from reverse_hr.evaluation_artifacts import collect_one
from reverse_hr.evaluation_material import prepare_one
from reverse_hr.grade_access import GradeAccess

signatures = signatures_fixture


def calibration():
    experts = [uuid4(), uuid4()]
    return dict(
        source_digest="a" * 64,
        scoring_version="competency-weighted-v1",
        reason="Synthetic independent held-out labels for mechanism tests",
        cases=[
            dict(
                case_id=str(uuid4()),
                scores={"structure": 100 if i < 10 else 0},
                labels=[dict(expert_id=str(e), passed=i < 10) for e in experts],
                holdout=True,
            )
            for i in range(20)
        ],
    )


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch):
    s = runner_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    s.author = token(uuid4(), ("content_admin",), amr=["mfa"])
    s.approver = token(uuid4(), ("content_admin",), amr=["mfa"])
    s.grade_reviewer_id = uuid4()
    s.grade_auth = token(s.grade_reviewer_id, ("assessment_reviewer",), amr=["mfa"])
    rules = dict(
        weights={"structure": 100},
        minimums={"structure": 60},
        pass_score=70,
        retry_seconds=3600,
        grade_change_seconds=7776000,
    )
    result = s.assessment.client.post(
        "/v1/grade-policies",
        json=dict(plan_version_id=s.version["plan_version_id"], rules=rules),
        headers=headers(s.author, "policy"),
    )
    assert result.status_code == 201, result.text
    s.policy_id = result.json()["policy_id"]
    s.calibration = calibration()
    result = s.assessment.client.post(
        f"/v1/grade-policies/{s.policy_id}/approve",
        json=s.calibration,
        headers=headers(s.approver, "approve", 1),
    )
    assert result.status_code == 200, result.text
    # Bind the already submitted synthetic fixture. Production admission is separately tested.
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(PracticalSession, str(s.session_id))
        row.grade_policy_id = s.policy_id
        row.grade_policy_digest = policy_digest(session.get(GradePolicy, s.policy_id))
    material_access = s.evaluation.app.state.material_access
    material_access.check_assessment = s.evaluation.app.state.processing_access.check_assessment
    original_sender = s.submitted._send

    def sender(route, raw, signature, **kwargs):
        if route in {"evaluation-artifact", "evaluation-artifact-admission", "stage-score"}:
            client = (
                s.workspace.client
                if route == "evaluation-artifact"
                else s.assessment.client
                if route == "evaluation-artifact-admission"
                else s.evaluation.client
            )
            response = client.post(
                "/internal/v1/" + route,
                content=raw,
                headers={"Content-Type": "application/json", "X-HR-Signature": signature},
            )
            assert response.status_code == 200, response.text
            return response.content, response.headers["X-HR-Signature"]
        return original_sender(route, raw, signature, **kwargs)

    s.submitted._send = sender
    s.workspace.app.state.artifact_permit_access._signatures = signatures["coding-workspace"]
    s.workspace.app.state.artifact_permit_access.send_permit = lambda raw, signature: sender(
        "evaluation-artifact-admission", raw, signature
    )
    artifact = ArtifactAccess(s.evaluation.app.state.settings)
    artifact._signatures = signatures["evaluation"]
    artifact.send_artifact = lambda raw, signature: sender("evaluation-artifact", raw, signature)
    s.evaluation.app.state.artifact_access = artifact
    s.assessment.app.state.grade_access = GradeAccess(s.assessment.app.state.settings)
    s.assessment.app.state.grade_access._signatures = signatures["assessment"]
    s.assessment.app.state.grade_access._send = sender
    assert prepare_one(s.evaluation.app.state.engine, material_access)
    assert collect_one(s.evaluation.app.state.engine, material_access, artifact)
    return s


def review(s, *, expected=100):
    for _ in range(len(s.definition.cases) + 2):
        assert tick(s)
    path = f"/v1/evaluation-reviews/stages/{s.stage_id}"
    reply = s.evaluation.client.get(path, headers=s.grade_auth)
    assert reply.status_code == 200, reply.text
    data = reply.json()
    assert data["trusted_test_points"] == {"shape": expected}
    reply = s.evaluation.client.post(
        path + "/reviews",
        headers=headers(s.grade_auth, "review", data["version"]),
        json=dict(
            reason="Synthetic human reviewed actual signed test evidence",
            decisions=[
                dict(
                    criterion_key="shape",
                    points=expected,
                    reason="Verified test proof",
                    test_proof_digest=data["test_proof_digest"],
                )
            ],
        ),
    )
    assert reply.status_code == 200, reply.text


def proposal(s):
    reply = s.assessment.client.get(
        f"/v1/assessment-grade-reviews/{s.session_id}", headers=s.grade_auth
    )
    assert reply.status_code == 200, reply.text
    return reply.json()


def decide(s, action="confirm", evidence=None, key="decision"):
    return s.assessment.client.post(
        f"/v1/assessment-grade-reviews/{s.session_id}/decisions",
        headers=headers(s.grade_auth, key),
        json=dict(
            action=action,
            evidence_digest=evidence,
            reason="Synthetic human grade decision with evidence",
        ),
    )


def test_signed_stage_aggregation_human_grade_and_independent_retry_cooldown(setup):
    s = setup
    assert proposal(s)["status"] == "awaiting_evidence"
    review(s)
    result = proposal(s)
    assert result["score"] == 100 and result["recommended_grade"] == "junior"
    assert result["confirmed_grade"] is None
    reply = decide(s, evidence=result["evidence_digest"])
    assert reply.status_code == 200, reply.text
    assert reply.json()["confirmed_grade"] == "junior"
    assert (
        decide(s, evidence=result["evidence_digest"]).json()["decision_id"]
        == reply.json()["decision_id"]
    )
    body = s.session_body | {"grade_policy_id": s.policy_id}
    retry = s.assessment.client.post(
        "/v1/assessment-sessions", json=body, headers=headers(s.auth, "repeat")
    )
    assert retry.status_code == 409
    with Session(s.assessment.app.state.engine) as session, session.begin():
        session.scalar(select(GradeDecision)).next_attempt_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
    retry = s.assessment.client.post(
        "/v1/assessment-sessions", json=body, headers=headers(s.auth, "repeat")
    )
    assert retry.status_code == 201, retry.text
    with Session(s.assessment.app.state.engine) as session:
        new = session.get(PracticalSession, retry.json()["session_id"])
        assert new.grade_policy_digest == policy_digest(session.get(GradePolicy, s.policy_id))
        grade = session.scalar(select(CandidateGrade))
        assert grade.change_available_at > datetime.now().replace(tzinfo=None)


def test_failed_assessment_preserves_existing_grade_and_technical_retry_not_zero(setup):
    s = setup
    s.executor.execute.return_value = __import__(
        "reverse_hr.domains.code_runner", fromlist=["Output"]
    ).Output(status="runtime_error", exit_code=1)
    review(s, expected=0)
    assert proposal(s)["score"] == 0
    with Session(s.assessment.app.state.engine) as session, session.begin():
        session.add(
            CandidateGrade(
                candidate_id=str(s.candidate),
                specialization="synthetic-backend",
                grade="middle",
                decision_id=str(uuid4()),
                changed_at=datetime.now(UTC),
                change_available_at=datetime.now(UTC) + timedelta(days=90),
            )
        )
    result = proposal(s)
    assert result["recommended_grade"] is None and result["confirmed_grade"] == "middle"
    assert decide(s, evidence=result["evidence_digest"]).status_code == 409
    reply = decide(s, "reject", result["evidence_digest"])
    assert reply.status_code == 200 and reply.json()["confirmed_grade"] == "middle"


def test_technical_failure_has_no_score_and_allows_retry(setup):
    s = setup
    reply = decide(s, "technical_failure")
    assert reply.status_code == 200, reply.text
    assert reply.json()["score"] is None and reply.json()["confirmed_grade"] is None
    retry = s.assessment.client.post(
        "/v1/assessment-sessions",
        json=s.session_body | {"grade_policy_id": s.policy_id},
        headers=headers(s.auth, "technical-repeat"),
    )
    assert retry.status_code == 201, retry.text


def test_missing_or_changed_evidence_cannot_confirm(setup):
    s = setup
    assert decide(s).status_code == 409
    review(s)
    assert decide(s, evidence="f" * 64).status_code == 409
    with Session(s.assessment.app.state.engine) as session, session.begin():
        session.get(PracticalSession, str(s.session_id)).grade_policy_digest = "f" * 64
    assert (
        s.assessment.client.get(
            f"/v1/assessment-grade-reviews/{s.session_id}", headers=s.grade_auth
        ).status_code
        == 409
    )


def test_calibration_is_independent_and_mechanically_verified(setup):
    s = setup
    assert (
        s.assessment.client.post(
            f"/v1/grade-policies/{s.policy_id}/approve",
            json=s.calibration,
            headers=headers(s.author, "self", 1),
        ).status_code
        == 403
    )
    with Session(s.assessment.app.state.engine) as session, session.begin():
        row = session.get(GradePolicy, s.policy_id)
        row.status, row.version, row.calibration, row.calibration_digest = "draft", 1, None, None
    bad = calibration()
    for case in bad["cases"]:
        case["scores"]["structure"] = 100
    reply = s.assessment.client.post(
        f"/v1/grade-policies/{s.policy_id}/approve",
        json=bad,
        headers=headers(s.approver, "bad-approval", 1),
    )
    assert reply.status_code == 409
    assert (
        s.assessment.client.get(f"/v1/grade-policies/{s.policy_id}", headers=s.author).json()[
            "calibrated"
        ]
        is False
    )


def test_privacy_removes_grade_decision_and_other_reviewers_command_cache(setup):
    s = setup
    review(s)
    result = proposal(s)
    assert decide(s, evidence=result["evidence_digest"]).status_code == 200
    with Session(s.assessment.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate))
    with Session(s.assessment.app.state.engine) as session:
        assert session.scalar(select(GradeDecision)) is None
        assert session.scalar(select(CandidateGrade)) is None


def test_grade_change_and_retry_limits_remain_separate(setup, monkeypatch):
    from types import SimpleNamespace

    from fastapi import HTTPException

    import reverse_hr.domains.assessment_grades as domain

    s = setup
    with Session(s.assessment.app.state.engine) as session, session.begin():
        policy = session.get(GradePolicy, s.policy_id)
        rules = domain.Rules.model_validate(policy.rules)
        monkeypatch.setattr(domain, "policy_for", lambda *args, **kwargs: (policy, rules))
        session.add(
            CandidateGrade(
                candidate_id=str(s.candidate),
                specialization="synthetic-backend",
                grade="junior",
                decision_id=str(uuid4()),
                changed_at=datetime.now(UTC),
                change_available_at=datetime.now(UTC) + timedelta(days=90),
            )
        )
        session.flush()
        with pytest.raises(HTTPException) as exc:
            domain.admission(
                session,
                s.candidate,
                SimpleNamespace(specialization="synthetic-backend", grade="middle"),
                s.policy_id,
            )
        assert exc.value.status_code == 409


def test_policy_retirement_and_missing_calibration_close_new_admission(setup):
    s = setup
    response = s.assessment.client.post(
        f"/v1/grade-policies/{s.policy_id}/retire",
        json={"reason": "Synthetic policy withdrawal"},
        headers=headers(s.approver, "retire", 2),
    )
    assert response.status_code == 200
    response = s.assessment.client.post(
        "/v1/assessment-sessions",
        json=s.session_body | {"grade_policy_id": s.policy_id},
        headers=headers(s.auth, "retired-admission"),
    )
    assert response.status_code == 409


def test_synthetic_self_review_cannot_confirm_candidate_grade(setup, token):
    s = setup
    auth = token(s.candidate, ("candidate", "assessment_reviewer"), amr=["mfa"])
    response = s.assessment.client.get(f"/v1/assessment-grade-reviews/{s.session_id}", headers=auth)
    assert response.status_code == 403


def test_calibration_contributor_deletion_retains_restricted_authorship(setup):
    from uuid import UUID

    from reverse_hr.domains.assessment_sessions import AssessmentSubject

    s = setup
    contributor = UUID(s.calibration["cases"][0]["labels"][0]["expert_id"])
    with Session(s.assessment.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(contributor))
    with Session(s.assessment.app.state.engine) as session:
        assert session.get(AssessmentSubject, str(contributor)).status == "restricted"
    response = s.assessment.client.post(
        "/v1/assessment-sessions",
        json=s.session_body | {"grade_policy_id": s.policy_id},
        headers=headers(s.auth, "blocked-contributor"),
    )
    assert response.status_code == 409


def test_policy_can_require_pinned_llm_proposal_before_grade(setup):
    import reverse_hr.domains.assessment_grades as domain
    from reverse_hr.grade_access import StageScore

    s = setup
    review(s)
    with Session(s.assessment.app.state.engine) as session:
        policy = session.get(GradePolicy, s.policy_id)
        rules = domain.Rules.model_validate(
            policy.rules
            | {"required_llm_model": "synthetic-model-v1", "required_llm_prompt_digest": "a" * 64}
        )
    stage = StageScore(
        snapshot_version=1,
        snapshot_digest="b" * 64,
        revision_id=s.selection["revision_id"],
        content_digest="c" * 64,
        task_key="sample",
        review_id=uuid4(),
        reviewer_id=uuid4(),
        criteria=[
            dict(
                criterion_key="shape",
                competency="structure",
                max_points=100,
                points=100,
                evidence_type="test_result",
            )
        ],
        score=100,
        evidence_digest="d" * 64,
    )
    assert domain.aggregate([stage], rules)[0] is None
    stage = stage.model_copy(
        update={
            "model_attempt_id": uuid4(),
            "llm_model": "synthetic-model-v1",
            "llm_prompt_digest": "a" * 64,
        }
    )
    assert domain.aggregate([stage], rules) == (100, {"structure": 100}, True)
