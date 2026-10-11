"""Pinned HTTPS wire adapter; responses and credential are explicitly synthetic."""

import json
from io import BytesIO
from types import SimpleNamespace

import pytest

from reverse_hr.services.assessment.generation_gateway import GenerationGateway
from tests.services.assessment.test_generation import setup as setup


@pytest.fixture
def wire(setup, tmp_path):
    s = setup
    path = tmp_path / "synthetic-provider-key"
    path.write_text("synthetic-key")
    s.app.state.settings.assessment_generation_key_file = str(path)
    gateway = GenerationGateway(s.app.state.settings)
    reply = dict(
        model=gateway.model,
        choices=[
            dict(
                finish_reason="stop",
                message=dict(role="assistant", content='{"valid":true,"issues":[]}'),
            )
        ],
        usage=dict(prompt_tokens=100, completion_tokens=20, total_tokens=120),
    )
    calls = []

    class Response(BytesIO):
        status = 200
        headers = {}

    def send(request, timeout):
        calls.append((request, timeout))
        return Response(json.dumps(reply).encode())

    gateway.opener = SimpleNamespace(open=send)
    return gateway, reply, calls


def test_validation_uses_separate_instruction_without_provider_tools(wire):
    gateway, _, calls = wire
    assert gateway.validate({"own_original_text": "Требования"}, {"task": "Оригинальная задача"})
    request, timeout = calls[0]
    body = json.loads(request.data)
    assert request.full_url == "https://generator.invalid/v1/chat/completions" and timeout == 30
    assert body["store"] is False and body["stream"] is False
    assert body["response_format"] == {"type": "json_object"} and "tools" not in body
    assert "synthetic-key" not in request.data.decode()


@pytest.mark.parametrize("bad", ["model", "refusal", "tools", "usage", "partial", "incoherent"])
def test_invalid_or_uncertain_provider_validation_is_not_accepted(wire, bad):
    gateway, reply, _ = wire
    message = reply["choices"][0]["message"]
    if bad == "model":
        reply["model"] = "unapproved-fallback"
    if bad == "refusal":
        message["refusal"] = "Cannot verify"
    if bad == "tools":
        message["tool_calls"] = [{}]
    if bad == "usage":
        reply["usage"]["total_tokens"] = False
    if bad == "partial":
        reply["choices"][0]["finish_reason"] = "length"
    if bad == "incoherent":
        message["content"] = '{"valid":"yes","issues":[]}'
    with pytest.raises(ValueError):
        gateway.validate({"own_original_text": "Требования"}, {"task": "Оригинальная задача"})
