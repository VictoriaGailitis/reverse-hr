"""Opt-in fixed-origin HTTPS intent parser; one bounded request, no tools or retries."""

import json
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from reverse_hr.domains.matching_governance import IntentInput, ParsedIntent
from reverse_hr.llm_configuration import GatewayConfiguration
from reverse_hr.llm_gateway import json_object
from reverse_hr.processing_access import NoRedirect

MAX_RESPONSE = 65536


class MatchingIntentGateway:
    def __init__(self, settings):
        if (
            settings.service_name != "matching"
            or not settings.matching_llm_enabled
            or not settings.matching_llm_model
            or settings.matching_llm_config is None
            or not settings.matching_llm_key_file
        ):
            raise ValueError("Matching intent gateway unavailable")
        self.config = GatewayConfiguration.model_validate(settings.matching_llm_config.model_dump())
        self.configuration = self.config.model_dump(mode="json")
        self.model = settings.matching_llm_model
        with Path(settings.matching_llm_key_file).open("rb") as stream:
            raw = stream.read(4097)
        key = raw.decode("ascii").strip()
        if len(raw) > 4096 or not key or any(ord(c) <= 32 or ord(c) >= 127 for c in key):
            raise ValueError("Invalid intent gateway credential file")
        self._key = key
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def parse(self, inputs, *, timeout_seconds):
        if (
            inputs.prompt_version != "employer-intent-v2"
            or inputs.instruction != IntentInput.model_fields["instruction"].default
            or not 1 <= timeout_seconds <= 15
        ):
            raise ValueError("Unpinned intent parser instruction")
        body = dict(
            model=self.model,
            store=False,
            stream=False,
            n=1,
            max_completion_tokens=self.config.max_output_tokens,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": inputs.instruction
                    + " JSON schema: "
                    + json.dumps(ParsedIntent.model_json_schema(), ensure_ascii=False),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {"text": inputs.text, "catalog": inputs.catalog.model_dump(mode="json")},
                        ensure_ascii=False,
                    ),
                },
            ],
        )
        wire = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        if (
            len(wire) > self.config.max_request_bytes
            or len(wire) + 1024 > self.config.max_input_tokens
        ):
            raise ValueError("Intent input limit exceeded")
        request = Request(
            self.config.origin.rstrip("/") + "/v1/chat/completions",
            data=wire,
            headers={
                "Authorization": "Bearer " + self._key,
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
            },
            method="POST",
        )
        with self.opener.open(request, timeout=timeout_seconds) as response:
            if (
                response.status != 200
                or response.headers.get("Content-Encoding", "identity") != "identity"
            ):
                raise ValueError("Invalid intent gateway response")
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("Oversized intent gateway response")
        data = json_object(raw)
        if (
            not isinstance(data, dict)
            or data.get("model") != self.model
            or not isinstance(data.get("choices"), list)
            or len(data["choices"]) != 1
        ):
            raise ValueError("Ambiguous or unpinned intent gateway model")
        choice = data["choices"][0]
        message = choice["message"]
        if (
            choice.get("finish_reason") != "stop"
            or message.get("role") != "assistant"
            or message.get("refusal")
            or message.get("tool_calls")
            or message.get("function_call")
            or not isinstance(message.get("content"), str)
        ):
            raise ValueError("Incomplete intent gateway response")
        usage = data["usage"]
        it, ot = usage["prompt_tokens"], usage["completion_tokens"]
        if (
            type(it) is not int
            or type(ot) is not int
            or not 0 <= it <= self.config.max_input_tokens
            or not 0 <= ot <= self.config.max_output_tokens
        ):
            raise ValueError("Invalid intent usage")
        return ParsedIntent.model_validate(json_object(message["content"]))
