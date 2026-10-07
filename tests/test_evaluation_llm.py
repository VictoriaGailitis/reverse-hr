"""Synthetic gateway proposals; no external inference or production calibration."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_evaluation_review import body as review_body
from test_evaluation_review import setup as review_setup
from test_event_transport import signatures as signatures_fixture

import reverse_hr.evaluation_llm as domain
from reverse_hr.domains.evaluation import EvaluationIntake
from reverse_hr.domains.evaluation_review import ReviewCommand
from reverse_hr.llm_configuration import GatewayConfiguration

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, monkeypatch, request):
    original = review_setup.__wrapped__(service, token, signatures, monkeypatch, request)
    target = original[0][0][0]
    stage = original[0][0][2].aggregate_id
    target.app.state.settings.evaluation_llm_enabled = True
    target.app.state.settings.evaluation_llm_model = "synthetic-model-v1"
    target.app.state.settings.evaluation_llm_config = GatewayConfiguration(
        origin="https://llm.invalid",
        max_input_tokens=32768,
        max_output_tokens=2048,
        input_microusd_per_million_tokens=1000000,
        output_microusd_per_million_tokens=2000000,
        stage_budget_microusd=150000,
    )
    return original, target, stage


def enqueue(s, key="model"):
    original, target, stage = s
    return target.client.post(
        f"/v1/evaluation-reviews/stages/{stage}/model-attempts", headers=headers(original[1], key)
    )


def run(s, gateway):
    _, target, _ = s
    return domain.run_one(
        target.app.state.engine,
        target.app.state.material_access,
        target.app.state.artifact_access,
        target.app.state.processing_access,
        gateway,
        timeout_seconds=1,
    )


def test_durable_model_proposal_metadata_never_sets_stage_score(setup):
    original, target, stage = setup
    reply = enqueue(setup)
    assert reply.status_code == 202, reply.text
    assert enqueue(setup).json()["attempt_id"] == reply.json()["attempt_id"]
    proposal = ReviewCommand.model_validate(review_body(original))
    gateway = SimpleNamespace(
        evaluate=lambda **kwargs: domain.ModelReply(
            proposal=proposal, input_tokens=123, output_tokens=45, cost_microusd=67
        )
    )
    assert run(setup, gateway)
    with Session(target.app.state.engine) as session:
        attempt = session.scalar(select(domain.ModelAttempt))
        assert attempt.status == "ready" and attempt.duration_ms is not None
        assert attempt.input_tokens == 123 and attempt.cost_microusd == 67
        assert session.get(EvaluationIntake, str(stage)).score is None
        attempt_id = attempt.attempt_id
    # Human explicitly accepts or edits the proposal and cites the model attempt.
    body = review_body(original) | {"model_attempt_id": attempt_id}
    reply = target.client.post(
        f"/v1/evaluation-reviews/stages/{stage}/reviews",
        json=body,
        headers=headers(original[1], "human", 3),
    )
    assert reply.status_code == 200, reply.text
    assert reply.json()["score"] == 80 and reply.json()["confirmed_grade"] is None


def test_gateway_failure_has_no_zero_and_retries_are_bounded(setup):
    _, target, stage = setup
    gateway = SimpleNamespace(evaluate=lambda **kwargs: (_ for _ in ()).throw(TimeoutError()))
    for number in range(3):
        assert enqueue(setup, f"attempt-{number}").status_code == 202
        assert run(setup, gateway)
    assert enqueue(setup, "fourth").status_code == 409
    with Session(target.app.state.engine) as session:
        attempts = list(session.scalars(select(domain.ModelAttempt)))
        assert all(a.status == "technical_failure" and a.output is None for a in attempts)
        assert session.get(EvaluationIntake, str(stage)).score is None


def test_unverified_model_points_cannot_certify_test_evidence(setup):
    original, target, stage = setup
    assert enqueue(setup).status_code == 202
    malicious = review_body(original)
    malicious["decisions"][0]["citations"][0]["file_digest"] = "f" * 64
    reply = domain.ModelReply(proposal=malicious, input_tokens=1, output_tokens=1, cost_microusd=0)
    assert run(setup, SimpleNamespace(evaluate=lambda **kwargs: reply))
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(domain.ModelAttempt)).status == "technical_failure"
    original_body = review_body(original)
    original_body["model_attempt_id"] = str(uuid4())
    assert (
        target.client.post(
            f"/v1/evaluation-reviews/stages/{stage}/reviews",
            json=original_body,
            headers=headers(original[1], "foreign", 3),
        ).status_code
        == 409
    )


def test_interruption_fences_late_reply_and_allows_new_attempt(setup):
    original, target, stage = setup
    reply = enqueue(setup)
    attempt_id = reply.json()["attempt_id"]
    path = f"/v1/evaluation-reviews/stages/{stage}/model-attempts/{attempt_id}/interrupt"
    assert target.client.post(path, headers=headers(original[1], "interrupt")).status_code == 200
    assert target.client.post(path, headers=headers(original[1], "interrupt")).status_code == 200
    assert enqueue(setup, "new-attempt").status_code == 202


def test_llm_disabled_by_default_without_a_provider(setup):
    _, target, _ = setup
    target.app.state.settings.evaluation_llm_enabled = False
    assert enqueue(setup).status_code == 409
    with pytest.raises(HTTPException):
        run(setup, None)
