"""Wire adapter tests use fake HTTPS responses and synthetic tariff configuration."""

import json
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.services.evaluation.domain.evaluation import EvaluationIntake
from reverse_hr.services.evaluation.evaluation_llm import ModelAttempt, ModelInput
from reverse_hr.services.evaluation.llm_gateway import ChatCompletionsGateway
from reverse_hr.shared.llm_configuration import GatewayConfiguration
from tests.services.evaluation.test_evaluation_llm import enqueue, run
from tests.services.evaluation.test_evaluation_llm import setup as model_setup
from tests.services.evaluation.test_evaluation_review import body as review_body
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture
setup = model_setup


@pytest.fixture
def wire(setup, tmp_path):
    original, target, stage = setup
    credential = tmp_path / "synthetic-key"
    credential.write_text("synthetic-key-never-sent\n")
    target.app.state.settings.evaluation_llm_key_file = str(credential)
    gateway = ChatCompletionsGateway(target.app.state.settings)
    with Session(target.app.state.engine) as session:
        row = session.get(EvaluationIntake, str(stage))
        inputs = ModelInput(material=row.material, source=row.source)
    reply = dict(
        model=gateway.model,
        choices=[
            dict(
                finish_reason="stop",
                message=dict(role="assistant", content=json.dumps(review_body(original))),
            )
        ],
        usage=dict(prompt_tokens=100, completion_tokens=200),
    )
    calls = []

    class Response(BytesIO):
        status = 200
        headers = {}

    def send(request, timeout):
        calls.append((request, timeout))
        return Response(json.dumps(reply).encode())

    gateway.opener = SimpleNamespace(open=send)
    return gateway, inputs, reply, calls


def test_wire_request_minimizes_data_and_records_estimated_usage(setup, wire):
    gateway, inputs, _, calls = wire
    assert enqueue(setup).status_code == 202
    assert run(setup, gateway)
    assert len(calls) == 1
    request, timeout = calls[0]
    body = json.loads(request.data)
    assert request.full_url == "https://llm.invalid/v1/chat/completions" and timeout == 1
    assert body["store"] is False and body["stream"] is False and body["n"] == 1
    assert body["response_format"]["json_schema"]["strict"] is True
    evidence = json.loads(body["messages"][1]["content"])
    assert set(evidence) == {"task", "files"}
    for key in ("consent_id", "candidate_id", "suite_pins", "test_cases"):
        assert key not in evidence
    assert evidence["files"][0]["file_digest"]
    _, target, _ = setup
    with Session(target.app.state.engine) as session:
        row = session.scalar(select(ModelAttempt))
        assert row.status == "ready" and row.cost_microusd == 500
        assert row.gateway_configuration == gateway.configuration
        assert "synthetic-key" not in json.dumps(row.gateway_configuration)


@pytest.mark.parametrize(
    "bad",
    [
        "model",
        "length",
        "refusal",
        "tools",
        "usage_bool",
        "usage_over_limit",
        "invalid_json",
        "duplicate_key",
        "extra_proposal",
        "test_claim",
        "many_choices",
    ],
)
def test_bad_response_fails_without_provider_retry(wire, bad):
    gateway, inputs, reply, calls = wire
    message = reply["choices"][0]["message"]
    if bad == "model":
        reply["model"] = "different-model"
    if bad == "length":
        reply["choices"][0]["finish_reason"] = "length"
    if bad == "refusal":
        message["refusal"] = "No"
    if bad == "tools":
        message["tool_calls"] = [{"id": "tool"}]
    if bad == "usage_bool":
        reply["usage"]["prompt_tokens"] = True
    if bad == "usage_over_limit":
        reply["usage"]["completion_tokens"] = 999999
    if bad == "invalid_json":
        message["content"] = "not JSON"
    if bad == "duplicate_key":
        message["content"] = '{"reason":"a","reason":"b","decisions":[]}'
    if bad in {"extra_proposal", "test_claim"}:
        data = json.loads(message["content"])
        data["unauthorized" if bad == "extra_proposal" else "model_attempt_id"] = str(uuid4())
        message["content"] = json.dumps(data)
    if bad == "many_choices":
        reply["choices"].append(reply["choices"][0])
    with pytest.raises((ValueError, KeyError)):
        gateway.evaluate(model=gateway.model, inputs=inputs, timeout_seconds=1)
    assert len(calls) == 1


def test_input_size_and_wrong_model_reject_before_sending(wire):
    gateway, inputs, _, calls = wire
    gateway.config.max_request_bytes = 1024
    with pytest.raises(ValueError):
        gateway.evaluate(model=gateway.model, inputs=inputs, timeout_seconds=1)
    with pytest.raises(ValueError):
        gateway.evaluate(model="other", inputs=inputs, timeout_seconds=1)
    assert calls == []


@pytest.mark.parametrize(
    "origin",
    [
        "http://llm.invalid",
        "https://user:password@llm.invalid",
        "https://llm.invalid/v1",
        "https://llm.invalid/?secret=x",
        "https://llm.invalid/#x",
    ],
)
def test_credentials_and_redirect_destinations_cannot_be_configured(origin):
    with pytest.raises(ValidationError):
        GatewayConfiguration(
            origin=origin,
            max_input_tokens=32768,
            max_output_tokens=2048,
            input_microusd_per_million_tokens=1000000,
            output_microusd_per_million_tokens=2000000,
            stage_budget_microusd=150000,
        )


def test_stage_budget_must_reserve_all_attempts(wire):
    gateway, _, _, _ = wire
    with pytest.raises(ValidationError):
        GatewayConfiguration.model_validate(gateway.configuration | {"stage_budget_microusd": 1})


def test_configuration_change_blocks_pending_attempt_before_remote_call(setup, wire):
    gateway, _, _, calls = wire
    assert enqueue(setup).status_code == 202
    gateway.configuration = gateway.configuration | {"origin": "https://another.invalid"}
    assert run(setup, gateway)
    assert calls == []
    _, target, _ = setup
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(ModelAttempt)).status == "blocked"
    target.app.state.settings.evaluation_llm_config = GatewayConfiguration.model_validate(
        gateway.configuration
    )
    assert enqueue(setup, "changed").status_code == 409


def test_unavailable_and_oversized_http_responses_are_not_retried(wire):
    gateway, inputs, _, calls = wire

    def fail(*args, **kwargs):
        calls.append(None)
        raise TimeoutError("Synthetic timeout")

    gateway.opener = SimpleNamespace(open=fail)
    with pytest.raises(TimeoutError):
        gateway.evaluate(model=gateway.model, inputs=inputs, timeout_seconds=1)
    assert len(calls) == 1
    response = BytesIO(b"x" * 262145)
    response.status, response.headers = 200, {}
    gateway.opener = SimpleNamespace(open=lambda *_, **__: response)
    with pytest.raises(ValueError):
        gateway.evaluate(model=gateway.model, inputs=inputs, timeout_seconds=1)


def test_restart_does_not_replay_unknown_running_charge(setup, wire):
    gateway, _, _, calls = wire
    assert enqueue(setup).status_code == 202
    _, target, _ = setup
    with Session(target.app.state.engine) as session, session.begin():
        session.scalar(select(ModelAttempt)).status = "running"
    assert not run(setup, gateway)
    assert calls == []


def test_source_denial_blocks_pending_without_remote_call(setup, wire):
    gateway, _, _, calls = wire
    assert enqueue(setup).status_code == 202
    _, target, _ = setup

    def deny(**_):
        raise HTTPException(409)

    target.app.state.material_access.fetch = deny
    assert run(setup, gateway)
    assert calls == []
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(ModelAttempt)).status == "blocked"


def test_missing_provider_config_rejects_request(setup):
    _, target, _ = setup
    target.app.state.settings.evaluation_llm_config = None
    assert enqueue(setup).status_code == 409


def test_compose_gateway_is_opt_in_and_only_worker_has_egress():
    import yaml

    compose = yaml.safe_load(Path("compose.yaml").read_text())
    worker = compose["services"]["evaluation-llm"]
    assert worker["profiles"] == ["llm"]
    assert worker["command"][-1] == "evaluate"
    assert worker["networks"] == ["backend", "llm-egress"]
    assert compose["services"]["evaluation"]["networks"] == ["backend"]
    assert not worker.get("ports")
    assert worker["read_only"] and worker["cap_drop"] == ["ALL"]
