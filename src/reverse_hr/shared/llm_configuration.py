"""Public immutable request limits; credentials are never part of the ledger."""

from urllib.parse import urlsplit

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract


class GatewayConfiguration(Contract):
    origin: str = Field(min_length=1, max_length=300)
    max_request_bytes: int = Field(default=65536, strict=True, ge=1024, le=262144)
    max_input_tokens: int = Field(strict=True, ge=1024, le=262144)
    max_output_tokens: int = Field(strict=True, ge=256, le=16384)
    input_microusd_per_million_tokens: int = Field(strict=True, ge=1, le=1000000000)
    output_microusd_per_million_tokens: int = Field(strict=True, ge=1, le=1000000000)
    stage_budget_microusd: int = Field(strict=True, ge=1, le=2147483647)

    def cost(self, inputs, outputs):
        return (
            inputs * self.input_microusd_per_million_tokens
            + outputs * self.output_microusd_per_million_tokens
            + 999999
        ) // 1000000

    @property
    def reservation(self):
        return self.cost(self.max_input_tokens, self.max_output_tokens)

    @model_validator(mode="after")
    def safe(self):
        parsed = urlsplit(self.origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("LLM requires a fixed HTTPS origin")
        if self.reservation * 3 > self.stage_budget_microusd:
            raise ValueError("Stage budget must cover all three reserved attempts")
        return self
