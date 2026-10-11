"""Minimal human-reviewed evidence; demo advice is never a grade decision."""

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract, Grade

Score = Annotated[int, Field(strict=True, ge=0, le=100)]


class QualificationEvidence(Contract):
    origin: Literal["human", "automatic"] = Field(
        default="human", exclude_if=lambda value: value == "human"
    )
    policy_id: UUID
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    assessed_at: datetime
    score: Score
    competency_scores: dict[str, Score] = Field(min_length=1, max_length=20)
    competency_minimums: dict[str, Score] = Field(default_factory=dict, max_length=20)
    next_attempt_at: datetime
    grade_change_available_at: datetime
    demo: Literal[True] = True

    @model_validator(mode="after")
    def coherent(self):
        if any(
            value.tzinfo is None
            for value in (self.assessed_at, self.next_attempt_at, self.grade_change_available_at)
        ) or self.assessed_at > datetime.now(UTC):
            raise ValueError("Aware completed assessment required")
        if not set(self.competency_minimums) <= set(self.competency_scores):
            raise ValueError("Unscored competency minimum")
        for key in self.competency_scores:
            if not key.strip() or len(key) > 64 or any(ord(c) < 32 for c in key):
                raise ValueError("Invalid competency key")
        return self


class QualificationAdvice(Contract):
    decision_id: UUID
    specialization: str
    assessed_at: datetime
    current_grade: Grade | None
    freshness: Literal["current", "aging", "expired"]
    repeat_recommended: bool
    retry_available: bool
    next_attempt_at: datetime
    grade_change_available_at: datetime
    recommended_next_grade: Grade | None
    feedback: list[str]
    policy_version: str = "qualification-advice-demo-v1"
    calibrated: bool = False
    demo: bool = True
