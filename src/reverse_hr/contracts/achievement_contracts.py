"""Minimal published achievement evidence; no contacts or external account identifiers."""

from datetime import date, datetime
from typing import Literal
from uuid import UUID

from pydantic import Field

from reverse_hr.contracts.core import Contract


class AchievementEvidence(Contract):
    achievement_id: UUID
    source_id: UUID
    version: int = Field(strict=True, ge=1)
    demo: bool = Field(strict=True)
    specialization: str | None
    format: Literal["individual", "team"]
    occurred_on: date | None = Field(default=None, exclude_if=lambda v: v is None)


class ResumeAchievement(AchievementEvidence):
    source_name: str = Field(min_length=1, max_length=150)
    event: str = Field(min_length=1, max_length=300)
    discipline: str = Field(min_length=1, max_length=150)
    occurred_on: date
    checked_at: datetime
    place: int | None = Field(default=None, ge=1)
    points: float | None = Field(default=None, ge=0)
