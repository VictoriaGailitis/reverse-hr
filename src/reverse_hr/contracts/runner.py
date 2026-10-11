"""Public data contract; no service persistence or HTTP handlers."""

from typing import Literal

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract


class Output(Contract):
    status: Literal["executed", "runtime_error", "limit_exceeded", "technical_error", "cancelled"]
    stdout: str = Field(default="", max_length=65536)
    stderr: str = Field(default="", max_length=65536)
    exit_code: int | None = Field(default=None, ge=-255, le=255, strict=True)
    reason: (
        Literal[
            "time_limit",
            "output_limit",
            "sandbox_failed",
            "executor_interrupted",
            "access_withdrawn",
            "user_cancelled",
            "admission_unavailable",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def coherent(self):
        try:
            size = len(self.stdout.encode("utf-8")) + len(self.stderr.encode("utf-8"))
        except UnicodeError as exc:
            raise ValueError("Invalid UTF-8 output") from exc
        if size > 65536:
            raise ValueError("Combined output exceeds limit")
        if self.status == "executed" and (self.exit_code != 0 or self.reason is not None):
            raise ValueError("Invalid successful exit")
        if self.status == "runtime_error" and (
            self.exit_code in (None, 0) or self.reason is not None
        ):
            raise ValueError("Invalid runtime exit")
        if self.status == "limit_exceeded" and self.reason not in {"time_limit", "output_limit"}:
            raise ValueError("Unconfirmed limit")
        if self.status in {"technical_error", "cancelled"}:
            if self.stdout or self.stderr or self.exit_code is not None:
                raise ValueError("Technical output must be redacted")
            allowed = (
                {"access_withdrawn", "user_cancelled"}
                if self.status == "cancelled"
                else {"sandbox_failed", "executor_interrupted", "admission_unavailable"}
            )
            if self.reason not in allowed:
                raise ValueError("Invalid technical reason")
        return self
