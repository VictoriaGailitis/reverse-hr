"""Explicit employment conditions; candidate declarations are never verified skills."""

from datetime import UTC, date, datetime
from typing import Literal

from pydantic import Field, field_validator, model_validator

from reverse_hr.contracts import Contract, SalaryRange

WorkFormat = Literal["remote", "hybrid", "onsite"]


class MonthlySalary(SalaryRange):
    minimum: int = Field(strict=True, gt=0, le=1000000000)
    maximum: int = Field(strict=True, gt=0, le=1000000000)


class StartWindow(Contract):
    earliest: date
    latest: date

    @field_validator("earliest", "latest", mode="before")
    @classmethod
    def calendar_date(cls, value):
        import re

        if isinstance(value, datetime) or type(value) in {bool, int, float}:
            raise ValueError("Use an explicit ISO calendar date")
        if isinstance(value, str) and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
            raise ValueError("Use an explicit ISO calendar date")
        return value

    @model_validator(mode="after")
    def ordered(self):
        if self.latest < self.earliest:
            raise ValueError("Explicit ordered start-date window required")
        return self


class EmploymentConditions(Contract):
    salary: MonthlySalary | None = None
    work_formats: list[WorkFormat] = Field(default_factory=list, max_length=3)
    start_window: StartWindow | None = None

    @model_validator(mode="after")
    def formats(self):
        if len(set(self.work_formats)) != len(self.work_formats):
            raise ValueError("Duplicate work format")
        self.work_formats = sorted(self.work_formats)
        return self


class CandidatePreferenceCommand(EmploymentConditions):
    salary_tolerance_percent: int = Field(default=0, strict=True, ge=0, le=25)
    share_in_matching: bool = Field(default=False, strict=True)
    confirmed: Literal[True]

    @model_validator(mode="before")
    @classmethod
    def explicit_confirmation(cls, value):
        if isinstance(value, dict) and value.get("confirmed") is not True:
            raise ValueError("Candidate must explicitly confirm preferences")
        return value

    @model_validator(mode="after")
    def tolerance_requires_salary(self):
        if self.salary is None and self.salary_tolerance_percent:
            raise ValueError("Tolerance requires an explicit salary range")
        return self


class CandidatePreferences(EmploymentConditions):
    salary_tolerance_percent: int = Field(default=0, strict=True, ge=0, le=25)
    version: int = Field(strict=True, ge=1)
    confirmed_at: datetime
    provenance: Literal["candidate_confirmed_self_description"] = (
        "candidate_confirmed_self_description"
    )

    @model_validator(mode="after")
    def provenance_time(self):
        if self.confirmed_at.tzinfo is None or self.confirmed_at > datetime.now(UTC):
            raise ValueError("Aware completed candidate confirmation required")
        if self.salary is None and self.salary_tolerance_percent:
            raise ValueError("Tolerance requires explicit range")
        return self


class ConditionComparison(Contract):
    eligible: bool
    salary: Literal["not_required", "compatible", "incompatible", "unknown"]
    work_format: Literal["not_required", "compatible", "incompatible", "unknown"]
    availability: Literal["not_required", "compatible", "incompatible", "unknown"]
    preference_version: int | None = None
    provenance: Literal["candidate_confirmed_self_description"] | None = None
    explanations: list[str]


def compare_conditions(conditions, preferences, *, maximum_age_days=90, now=None):
    """Only overlapping explicit ranges are compatible; unknown never means unlimited."""
    now = now or datetime.now(UTC)
    results = dict(salary="not_required", work_format="not_required", availability="not_required")
    explanations = []
    required = (
        conditions.salary is not None,
        bool(conditions.work_formats),
        conditions.start_window is not None,
    )
    if preferences is None or (now - preferences.confirmed_at).days > maximum_age_days:
        for key, needed in zip(results, required, strict=True):
            if needed:
                results[key] = "unknown"
        if any(required):
            explanations.append("Current candidate-confirmed public preferences are unavailable.")
    else:
        if conditions.salary is not None:
            candidate = preferences.salary
            if candidate is None or candidate.tax_basis != conditions.salary.tax_basis:
                results["salary"] = "unknown"
                explanations.append(
                    "Salary missing or gross/net bases differ; no conversion is inferred."
                )
            else:
                tolerance = preferences.salary_tolerance_percent
                lower = candidate.minimum * (100 - tolerance) // 100
                upper = (candidate.maximum * (100 + tolerance) + 99) // 100
                compatible = max(lower, conditions.salary.minimum) <= min(
                    upper, conditions.salary.maximum
                )
                results["salary"] = "compatible" if compatible else "incompatible"
                explanations.append(
                    f"Explicit RUB/month {candidate.tax_basis} ranges compared; "
                    f"candidate-confirmed tolerance {tolerance}% applied."
                )
        if conditions.work_formats:
            if not preferences.work_formats:
                results["work_format"] = "unknown"
            else:
                results["work_format"] = (
                    "compatible"
                    if set(conditions.work_formats) & set(preferences.work_formats)
                    else "incompatible"
                )
            explanations.append("Work formats compared with the candidate's stated choices.")
        if conditions.start_window:
            if preferences.start_window is None:
                results["availability"] = "unknown"
            else:
                lower = max(
                    conditions.start_window.earliest, preferences.start_window.earliest, now.date()
                )
                upper = min(conditions.start_window.latest, preferences.start_window.latest)
                results["availability"] = "compatible" if lower <= upper else "incompatible"
            explanations.append(
                "Only explicit future/current start windows overlap; "
                "employment status is not inferred."
            )
    return ConditionComparison(
        eligible=all(v in {"not_required", "compatible"} for v in results.values()),
        **results,
        explanations=explanations,
        preference_version=preferences.version if preferences else None,
        provenance=preferences.provenance if preferences else None,
    )
