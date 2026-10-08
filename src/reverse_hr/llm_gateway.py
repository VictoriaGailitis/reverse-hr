"""Single bounded Chat Completions request; no retry, fallback, tools or redirects.

Protocol reference: https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create
Cost is an estimate from operator-configured rates, not a provider invoice.
"""

import hashlib
import json
from pathlib import Path
from urllib.request import ProxyHandler, Request, build_opener

from reverse_hr.domains.evaluation_review import ReviewCommand
from reverse_hr.evaluation_llm import PROMPT, ModelReply
from reverse_hr.llm_configuration import GatewayConfiguration
from reverse_hr.processing_access import NoRedirect

MAX_RESPONSE = 262144


def json_object(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON member")
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("Invalid JSON number")),
    )


def object_schema(properties):
    return dict(
        type="object", properties=properties, required=list(properties), additionalProperties=False
    )


def proposal_schema(practical=False):
    citation = object_schema(
        dict(
            path={"type": "string"},
            file_digest={"type": "string"},
            start_line={"type": "integer"},
            end_line={"type": "integer"},
        )
    )
    criterion = object_schema(
        dict(
            criterion_key={"type": "string"},
            points={"type": ["integer", "null"]},
            reason={"type": "string"},
            citations={"type": "array", "items": citation},
        )
    )
    if practical:
        recording = object_schema(
            dict(
                snapshot_id={"type": "string"},
                recording_digest={"type": "string"},
                transcript_id={"type": "string"},
                transcript_digest={"type": "string"},
                segment_key={"type": "string"},
                start_ms={"type": "integer"},
                end_ms={"type": "integer"},
            )
        )
        board = object_schema(
            dict(
                snapshot_id={"type": "string"},
                snapshot_digest={"type": "string"},
                object_id={"type": "string"},
                object_digest={"type": "string"},
            )
        )
        criterion["properties"].update(
            recording_citations={"type": "array", "items": recording},
            board_citations={"type": "array", "items": board},
        )
        criterion["required"] = list(criterion["properties"])
    return object_schema(
        dict(decisions={"type": "array", "items": criterion}, reason={"type": "string"})
    )


class ChatCompletionsGateway:
    def __init__(self, settings):
        if (
            settings.service_name != "evaluation"
            or not settings.evaluation_llm_enabled
            or not settings.evaluation_llm_model
            or settings.evaluation_llm_config is None
            or not settings.evaluation_llm_key_file
        ):
            raise ValueError("LLM gateway configuration unavailable")
        self.configuration = GatewayConfiguration.model_validate(
            settings.evaluation_llm_config.model_dump()
        ).model_dump(mode="json")
        self.config = GatewayConfiguration.model_validate(self.configuration)
        self.model = settings.evaluation_llm_model
        with Path(settings.evaluation_llm_key_file).open("rb") as stream:
            raw = stream.read(4097)
        key = raw.decode("ascii").strip()
        if len(raw) > 4096 or not key or any(ord(c) <= 32 or ord(c) >= 127 for c in key):
            raise ValueError("Invalid LLM credential file")
        self._key = key
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    def evaluate(self, *, model, inputs, timeout_seconds):
        if model != self.model or not 1 <= timeout_seconds <= 30 or inputs.instruction != PROMPT:
            raise ValueError("Unpinned gateway input")
        # Deliberately omit candidate/session IDs, consent, suite pins and case metadata.
        from reverse_hr.domains.coding_workspace import FilesCommand

        practical = not isinstance(inputs.source, FilesCommand)
        evidence = dict(task=inputs.material.task.model_dump(mode="json"))
        if practical:
            evidence["practical"] = inputs.source.model_dump(mode="json")
        else:
            evidence["files"] = [
                dict(
                    path=f.path,
                    content=f.content,
                    file_digest=hashlib.sha256(f.content.encode()).hexdigest(),
                )
                for f in inputs.source.files
            ]
        body = dict(
            model=model,
            store=False,
            stream=False,
            n=1,
            max_completion_tokens=self.config.max_output_tokens,
            messages=[
                dict(role="system", content=PROMPT),
                dict(role="user", content=json.dumps(evidence, ensure_ascii=False)),
            ],
            response_format=dict(
                type="json_schema",
                json_schema=dict(
                    name="rubric_proposal", strict=True, schema=proposal_schema(practical)
                ),
            ),
        )
        wire = json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode()
        # A conservative byte guard, not a model-specific tokenizer or billing guarantee.
        if (
            len(wire) > self.config.max_request_bytes
            or len(wire) + 1024 > self.config.max_input_tokens
        ):
            raise ValueError("LLM request exceeds configured input limit")
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
                raise ValueError("Invalid gateway response")
            raw = response.read(MAX_RESPONSE + 1)
        if len(raw) > MAX_RESPONSE:
            raise ValueError("Oversized gateway response")
        data = json_object(raw)
        if (
            data.get("model") != model
            or not isinstance(data.get("choices"), list)
            or len(data["choices"]) != 1
        ):
            raise ValueError("Unpinned or ambiguous model response")
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
            raise ValueError("Incomplete model response")
        usage = data["usage"]
        it, ot = usage["prompt_tokens"], usage["completion_tokens"]
        if (
            type(it) is not int
            or type(ot) is not int
            or not 0 <= it <= self.config.max_input_tokens
            or not 0 <= ot <= self.config.max_output_tokens
        ):
            raise ValueError("Invalid gateway usage")
        proposal = ReviewCommand.model_validate(json_object(message["content"]))
        return ModelReply(
            proposal=proposal,
            input_tokens=it,
            output_tokens=ot,
            cost_microusd=self.config.cost(it, ot),
        )
