"""Synthetic HTTPS wire responses; no credentials or provider requests."""

import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from reverse_hr.services.matching.domain.matching_governance import IntentInput, Vocabulary
from reverse_hr.services.matching.matching_gateway import MatchingIntentGateway
from reverse_hr.shared.llm_configuration import GatewayConfiguration


@pytest.fixture
def wire(tmp_path):
    credential = tmp_path / "synthetic-key"
    credential.write_text("synthetic-key-never-sent")
    settings = SimpleNamespace(
        service_name="matching",
        matching_llm_enabled=True,
        matching_llm_model="pinned-model",
        matching_llm_key_file=str(credential),
        matching_llm_config=GatewayConfiguration(
            origin="https://llm.invalid",
            max_input_tokens=20000,
            max_output_tokens=2000,
            input_microusd_per_million_tokens=1000,
            output_microusd_per_million_tokens=1000,
            stage_budget_microusd=100000,
        ),
    )
    gateway = MatchingIntentGateway(settings)
    inputs = IntentInput(
        text="backend middle python",
        catalog=Vocabulary(
            version="v1",
            specializations=["backend"],
            entries=[{"key": "python", "evidence_keys": ["python"]}],
        ),
    )
    reply = {
        "model": "pinned-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(
                        {
                            "specialization": "backend",
                            "grade": "middle",
                            "mandatory": ["python"],
                            "citations": {
                                "specialization": "backend",
                                "grade": "middle",
                                "mandatory:python": "python",
                            },
                        }
                    ),
                },
            }
        ],
        "usage": {"prompt_tokens": 100, "completion_tokens": 100},
    }
    calls = []

    class Response(BytesIO):
        status = 200
        headers = {}

    def send(request, timeout):
        calls.append((request, timeout))
        return Response(json.dumps(reply).encode())

    gateway.opener = SimpleNamespace(open=send)
    return gateway, inputs, reply, calls


def test_intent_wire_pins_model_and_minimizes_context(wire):
    gateway, inputs, _, calls = wire
    result = gateway.parse(inputs, timeout_seconds=15)
    assert result.grade == "middle"
    request, timeout = calls[0]
    assert timeout == 15 and request.full_url == "https://llm.invalid/v1/chat/completions"
    body = json.loads(request.data)
    assert body["store"] is False and body["stream"] is False and body["model"] == "pinned-model"
    assert set(json.loads(body["messages"][1]["content"])) == {"text", "catalog"}
    assert "candidate_id" not in request.data.decode()


@pytest.mark.parametrize(
    "bad",
    [
        "model",
        "refusal",
        "tools",
        "truncated",
        "usage_bool",
        "usage_limit",
        "duplicate_json",
        "nan",
        "extra_field",
    ],
)
def test_intent_wire_rejects_invalid_provider_response(wire, bad):
    gateway, inputs, reply, _ = wire
    message = reply["choices"][0]["message"]
    if bad == "model":
        reply["model"] = "different-model"
    elif bad == "refusal":
        message["refusal"] = "refused"
    elif bad == "tools":
        message["tool_calls"] = [{"id": "irrelevant"}]
    elif bad == "truncated":
        reply["choices"][0]["finish_reason"] = "length"
    elif bad == "usage_bool":
        reply["usage"]["prompt_tokens"] = True
    elif bad == "usage_limit":
        reply["usage"]["completion_tokens"] = 99999
    elif bad == "duplicate_json":
        message["content"] = '{"grade":"middle","grade":"senior"}'
    elif bad == "nan":
        message["content"] = '{"grade":NaN}'
    else:
        message["content"] = '{"grade":"middle","candidate_id":"unexpected"}'
    with pytest.raises(ValueError):
        gateway.parse(inputs, timeout_seconds=15)


def test_intent_gateway_input_limits_are_enforced_before_network(wire):
    gateway, inputs, _, calls = wire
    gateway.config.max_request_bytes = 1024
    with pytest.raises(ValueError):
        gateway.parse(inputs, timeout_seconds=15)
    assert not calls
