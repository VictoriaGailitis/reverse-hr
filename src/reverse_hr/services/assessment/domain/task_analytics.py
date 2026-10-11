"""Read-only item analysis; grades and thresholds are never changed by a report."""

from datetime import UTC, datetime
from itertools import combinations
from math import sqrt
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.automation import human_owners
from reverse_hr.contracts.core import Contract, Grade
from reverse_hr.protocols.grade_access import StageScore
from reverse_hr.services.assessment.domain.assessment import ContentRevision
from reverse_hr.services.assessment.domain.assessment_appeals import effective_decision
from reverse_hr.services.assessment.domain.assessment_generation import (
    GenerationJob,
    GenerationReference,
)
from reverse_hr.services.assessment.domain.assessment_grades import GradeDecision
from reverse_hr.services.assessment.domain.assessment_sessions import PracticalSession
from reverse_hr.shared.auth import Actor


class Bands(Contract):
    normal_from: int = Field(default=50, strict=True, ge=1, le=99)
    good_from: int = Field(default=80, strict=True, ge=2, le=100)

    @model_validator(mode="after")
    def ordered(self):
        if self.normal_from >= self.good_from:
            raise ValueError("Normal threshold must be lower than good threshold")
        return self


class Scale(Contract):
    by_grade: dict[Grade, Bands] = Field(default_factory=lambda: {g: Bands() for g in Grade})
    minimum_group_size: int = Field(default=10, strict=True, ge=5, le=1000)

    @model_validator(mode="after")
    def complete(self):
        if set(self.by_grade) != set(Grade):
            raise ValueError("All four grade bands are required")
        return self


class ReportQuery(Contract):
    scope: Literal["task", "reference_version", "reference_family"] = "task"
    scope_id: UUID
    task_key: str | None = Field(default=None, min_length=1, max_length=100)
    since: datetime
    until: datetime
    scale: Scale = Field(default_factory=Scale)

    @model_validator(mode="after")
    def bounded(self):
        if (self.scope == "task") != (self.task_key is not None):
            raise ValueError("Task key required only for a task report")
        if self.since.tzinfo is None or self.until.tzinfo is None or self.until <= self.since:
            raise ValueError("A timezone-aware nonempty interval is required")
        if (self.until - self.since).total_seconds() > 366 * 86400:
            raise ValueError("Report interval must not exceed one year")
        return self


class Observation(Contract):
    profile_key: str = Field(min_length=1, max_length=100)
    score: float = Field(strict=True, ge=0, le=100, allow_inf_nan=False)
    target_grade: Grade
    independent_grade: Grade | None = None
    rest_score: float | None = Field(default=None, ge=0, le=100, allow_inf_nan=False)


class Simulation(Contract):
    scale: Scale = Field(default_factory=Scale)
    observations: list[Observation] = Field(max_length=5000)
    label_source: Literal["synthetic", "expert"] = "synthetic"
    reason: str = Field(min_length=1, max_length=2000)

    @model_validator(mode="after")
    def independent_profiles(self):
        keys = [item.profile_key for item in self.observations]
        if len(keys) != len(set(keys)):
            raise ValueError("Only one observation per profile per report")
        return self


class Bucket(Contract):
    quality: Literal["poor", "normal", "good"]
    count: int
    percent: float


class GradeDistribution(Contract):
    grade: Grade
    count: int
    mean_score: float | None
    bands: Bands
    buckets: list[Bucket]
    sufficient: bool


class Contrast(Contract):
    lower_grade: Grade
    upper_grade: Grade
    lower_count: int
    upper_count: int
    normal_or_better_difference: float | None
    good_difference: float | None
    status: Literal["available", "insufficient_data"]


class AnalyticsReport(Contract):
    source: Literal["live_demo", "synthetic", "expert"]
    scale: Scale
    sample_count: int
    independent_label_count: int
    target_distributions: list[GradeDistribution]
    independent_distributions: list[GradeDistribution]
    contrasts: list[Contrast]
    corrected_item_total_correlation: float | None
    correlation_count: int
    correlation_status: Literal["available", "insufficient_data", "constant_scores"]
    excluded: dict[str, int] = Field(default_factory=dict)
    warnings: list[str]


def quality(score, bands):
    return "poor" if score < bands.normal_from else "normal" if score < bands.good_from else "good"


def distributions(items, field, scale):
    result = []
    for grade in Grade:
        rows = [item for item in items if getattr(item, field) == grade]
        counts = {key: 0 for key in ("poor", "normal", "good")}
        for item in rows:
            counts[quality(item.score, scale.by_grade[grade])] += 1
        result.append(
            GradeDistribution(
                grade=grade,
                count=len(rows),
                bands=scale.by_grade[grade],
                mean_score=round(sum(item.score for item in rows) / len(rows), 3) if rows else None,
                buckets=[
                    Bucket(
                        quality=key,
                        count=count,
                        percent=round(count * 100 / len(rows), 3) if rows else 0,
                    )
                    for key, count in counts.items()
                ],
                sufficient=len(rows) >= scale.minimum_group_size,
            )
        )
    return result


def summarize(items, scale, source, excluded=None):
    target = distributions(items, "target_grade", scale)
    independent = distributions(items, "independent_grade", scale)
    contrasts = []
    # Use ONE threshold (the higher level's standard) for both groups in a contrast.
    for lower, upper in combinations(Grade, 2):
        a = [item.score for item in items if item.independent_grade == lower]
        b = [item.score for item in items if item.independent_grade == upper]
        enough = min(len(a), len(b)) >= scale.minimum_group_size
        bands = scale.by_grade[upper]

        def difference(threshold, a=a, b=b, enough=enough):
            return (
                round(
                    sum(v >= threshold for v in b) / len(b)
                    - sum(v >= threshold for v in a) / len(a),
                    6,
                )
                if enough
                else None
            )

        contrasts.append(
            Contrast(
                lower_grade=lower,
                upper_grade=upper,
                lower_count=len(a),
                upper_count=len(b),
                normal_or_better_difference=difference(bands.normal_from),
                good_difference=difference(bands.good_from),
                status="available" if enough else "insufficient_data",
            )
        )
    pairs = [(item.score, item.rest_score) for item in items if item.rest_score is not None]
    correlation, status = None, "insufficient_data"
    if len(pairs) >= scale.minimum_group_size:
        xbar = sum(x for x, _ in pairs) / len(pairs)
        ybar = sum(y for _, y in pairs) / len(pairs)
        denominator = sqrt(
            sum((x - xbar) ** 2 for x, _ in pairs) * sum((y - ybar) ** 2 for _, y in pairs)
        )
        if denominator:
            correlation = round(sum((x - xbar) * (y - ybar) for x, y in pairs) / denominator, 6)
            status = "available"
        else:
            status = "constant_scores"
    return AnalyticsReport(
        source=source,
        scale=scale,
        sample_count=len(items),
        independent_label_count=sum(i.independent_grade is not None for i in items),
        target_distributions=target,
        independent_distributions=independent,
        contrasts=contrasts,
        corrected_item_total_correlation=correlation,
        correlation_count=len(pairs),
        correlation_status=status,
        excluded=excluded or {},
        warnings=[
            "Descriptive analysis; no automatic grade or publication changes.",
            "Target grade is not an independent proficiency label.",
            "One latest observation per profile; technical failures are not zero scores.",
            "Different generated variants are not assumed psychometrically equivalent.",
            "Differences and correlations are estimates, not causal or calibrated accuracy claims.",
        ],
    )


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def collect(request, session, query):
    if query.scope == "task":
        revision = session.get(ContentRevision, str(query.scope_id))
        if revision is None:
            raise HTTPException(404)
        from reverse_hr.services.assessment.domain.company_tasks import CompanyProposal

        if session.scalar(
            select(CompanyProposal.proposal_id).where(
                CompanyProposal.revision_id == revision.revision_id
            )
        ):
            raise HTTPException(403)
        if query.task_key not in {t["key"] for t in revision.content["tasks"]}:
            raise HTTPException(404)
        revisions = {str(query.scope_id)}
    else:
        refs = list(
            session.scalars(
                select(GenerationReference).where(
                    (
                        GenerationReference.version_id
                        if query.scope == "reference_version"
                        else GenerationReference.reference_id
                    )
                    == str(query.scope_id)
                )
            )
        )
        if not refs:
            raise HTTPException(404)
        if any(ref.organization_id for ref in refs):
            raise HTTPException(403)
        revisions = set(
            session.scalars(
                select(GenerationJob.revision_id).where(
                    GenerationJob.version_id.in_([ref.version_id for ref in refs]),
                    GenerationJob.revision_id.is_not(None),
                )
            )
        )
    rows = list(
        session.execute(
            select(GradeDecision, PracticalSession)
            .join(PracticalSession, PracticalSession.session_id == GradeDecision.session_id)
            .where(
                PracticalSession.created_at >= utc(query.since),
                PracticalSession.created_at < utc(query.until),
            )
            .order_by(PracticalSession.created_at, GradeDecision.decision_id)
            .limit(5001)
        )
    )
    if len(rows) > 5000:
        raise HTTPException(409, "Narrow the interval; report exceeds 5000 sessions")
    excluded = {"technical_or_unscored": 0, "restricted": 0, "superseded_attempts": 0}
    latest = {}
    for original, run in rows:
        specs = [
            spec
            for spec in run.stages
            if spec["revision_id"] in revisions
            and (query.task_key is None or spec["task_key"] == query.task_key)
        ]
        if not specs:
            continue
        try:
            request.app.state.processing_access.check(UUID(run.candidate_id))
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
            excluded["restricted"] += 1
            continue
        decision = effective_decision(session, original)
        try:
            for owner in human_owners([decision.reviewer_id]):
                request.app.state.processing_access.check(UUID(owner))
        except HTTPException as exc:
            if exc.status_code not in {403, 404, 409}:
                raise
            excluded["restricted"] += 1
            continue
        if decision.status not in {"confirmed", "rejected"} or decision.score is None:
            excluded["technical_or_unscored"] += 1
            continue
        scores = [StageScore.model_validate(value) for value in decision.evidence.get("stages", [])]
        chosen = [
            score
            for score in scores
            if any(
                str(score.revision_id) == spec["revision_id"] and score.task_key == spec["task_key"]
                for spec in specs
            )
        ]
        if not chosen or any(score.score is None for score in scores):
            excluded["technical_or_unscored"] += 1
            continue
        # Only independently confirmed results that already existed when this session started.
        prior = [
            effective_decision(session, old)
            for old in session.scalars(
                select(GradeDecision).where(
                    GradeDecision.candidate_id == run.candidate_id,
                    GradeDecision.specialization == original.specialization,
                    GradeDecision.created_at < run.created_at,
                )
            )
        ]
        grades = []
        for old in prior:
            if old.status != "confirmed" or utc(old.created_at) >= utc(run.created_at):
                continue
            try:
                for owner in human_owners([old.reviewer_id]):
                    request.app.state.processing_access.check(UUID(owner))
            except HTTPException as exc:
                if exc.status_code not in {403, 404, 409}:
                    raise
                continue
            grades.append(Grade(old.target_grade))
        label = max(grades, key=lambda grade: list(Grade).index(grade)) if grades else None
        rest = [score.score for score in scores if score not in chosen]
        item = Observation(
            profile_key=run.candidate_id,
            target_grade=original.target_grade,
            independent_grade=label,
            score=sum(score.score for score in chosen) / len(chosen),
            rest_score=sum(rest) / len(rest) if rest else None,
        )
        if run.candidate_id in latest:
            excluded["superseded_attempts"] += 1
        latest[run.candidate_id] = item
    # Repeat Privacy checks before returning aggregates; no persisted report can outlive consent.
    for candidate in latest:
        request.app.state.processing_access.check(UUID(candidate))
    return summarize(list(latest.values()), query.scale, "live_demo", excluded)


router = APIRouter(prefix="/v1/task-analytics", tags=["task-analytics"])


@router.post("/report", response_model=AnalyticsReport)
def report(request: Request, response: Response, actor: Actor, body: ReportQuery):
    response.headers["Cache-Control"] = "private, no-store"
    actor.require("content_admin", mfa=True)
    request.app.state.processing_access.check(actor.subject)
    with Session(request.app.state.engine) as session:
        return collect(request, session, body)


@router.post("/simulate", response_model=AnalyticsReport)
def simulate(request: Request, response: Response, actor: Actor, body: Simulation):
    response.headers["Cache-Control"] = "private, no-store"
    actor.require("content_admin", mfa=True)
    request.app.state.processing_access.check(actor.subject)
    return summarize(body.observations, body.scale, body.label_source)
