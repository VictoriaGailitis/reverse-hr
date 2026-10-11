from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.suite_validation import (
    CaseCapture,
    SuitePin,
)

VERDICT_CONTEXT = b"reverse-hr.suite-validation-verdict.v1\0"


class SuiteVerdict(Contract):
    version: Literal[1] = 1
    producer: Literal["code-runner"] = "code-runner"
    purpose: Literal["suite-validation-verdict"] = "suite-validation-verdict"
    validation_id: UUID
    owner_id: UUID
    pin: SuitePin
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    captures_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    captures_count: int = Field(strict=True, ge=3, le=120)
    verdict: Literal["accepted", "rejected"]
    completed_at: datetime
    demo: Literal[True] = True
    scoring_enabled: Literal[False] = False


class CaptureMatrix(Contract):
    captures: list[CaseCapture] = Field(min_length=3, max_length=120)
