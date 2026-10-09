"""Human demo rubric decisions with exact artifact citations and immutable revisions."""

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field, field_validator, model_serializer, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import enqueue
from reverse_hr.domains.coding_workspace import File, FilesCommand
from reverse_hr.domains.evaluation import EvaluationBase, EvaluationIntake, subject_lock
from reverse_hr.evaluation_access import PinnedMaterial
from reverse_hr.events import EventEnvelope
from reverse_hr.practical_evidence import (
    BoardCitation,
    PracticalSource,
    RecordingCitation,
    Source,
    sha,
    source_digest,
    source_model,
)


class ReviewRecord(EvaluationBase):
    __tablename__ = "evaluation_reviews"
    __table_args__ = (UniqueConstraint("stage_id", "number"),)
    review_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stage_id: Mapped[str] = mapped_column(ForeignKey("evaluation_intakes.stage_id"), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    number: Mapped[int]
    intake_version: Mapped[int]
    model_attempt_id: Mapped[str | None] = mapped_column(String(36))
    decisions: Mapped[list] = mapped_column(JSON)
    score: Mapped[int | None]
    reason: Mapped[str] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Citation(Contract):
    path: str = Field(min_length=1, max_length=200)
    file_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    start_line: int = Field(strict=True, ge=1, le=65537)
    end_line: int = Field(strict=True, ge=1, le=65537)

    @field_validator("path")
    @classmethod
    def safe(cls, value):
        return File.safe_path(value)

    @model_validator(mode="after")
    def ordered(self):
        if self.end_line < self.start_line:
            raise ValueError("Invalid line range")
        return self


class CriterionDecision(Contract):
    criterion_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    points: int | None = Field(default=None, strict=True, ge=0, le=100)
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    test_proof_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    citations: list[Citation] = Field(default_factory=list, max_length=10)
    recording_citations: list[RecordingCitation] = Field(default_factory=list, max_length=10)
    board_citations: list[BoardCitation] = Field(default_factory=list, max_length=10)

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        result = handler(self)
        for key in ("recording_citations", "board_citations"):
            if not result.get(key):
                result.pop(key, None)
        return result

    @model_validator(mode="after")
    def evidence(self):
        evidence = [
            bool(self.citations),
            bool(self.recording_citations),
            bool(self.board_citations),
            bool(self.test_proof_digest),
        ]
        if (self.points is not None) != any(evidence) or sum(evidence) > 1:
            raise ValueError(
                "Scored criteria require evidence; missing evidence leaves points unset"
            )
        if len({(c.path, c.start_line, c.end_line) for c in self.citations}) != len(self.citations):
            raise ValueError("Duplicate citations")
        return self


class ReviewCommand(Contract):
    model_attempt_id: UUID | None = None
    decisions: list[CriterionDecision] = Field(min_length=1, max_length=20)
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")

    @model_validator(mode="after")
    def unique(self):
        if len({d.criterion_key for d in self.decisions}) != len(self.decisions):
            raise ValueError("Duplicate criterion decisions")
        return self


class ReviewView(ReviewCommand):
    review_id: UUID
    reviewer_id: UUID
    number: int
    intake_version: int
    score: int | None = Field(ge=0, le=100)
    created_at: datetime


class ReviewResult(Contract):
    stage_id: UUID
    version: int
    status: Literal["artifact_ready", "needs_evidence", "reviewed"]
    score: int | None = Field(ge=0, le=100)
    confirmed_grade: None = None
    latest: ReviewView | None
    demo: Literal[True] = True


class ReviewWorkspace(ReviewResult):
    material: PinnedMaterial
    source: Source
    trusted_test_points: dict[str, int | None] = Field(default_factory=dict)
    test_proof_digest: str | None = None


router = APIRouter(prefix="/v1/evaluation-reviews", tags=["evaluation-review"])


def review_view(row):
    timestamp = row.created_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return ReviewView(
        review_id=row.review_id,
        model_attempt_id=row.model_attempt_id,
        reviewer_id=row.reviewer_id,
        number=row.number,
        intake_version=row.intake_version,
        score=row.score,
        reason=row.reason,
        decisions=row.decisions,
        created_at=timestamp,
    )


def result(session, row):
    latest = (
        session.scalar(
            select(ReviewRecord).where(
                ReviewRecord.stage_id == row.stage_id, ReviewRecord.number == row.review_number
            )
        )
        if row.review_number
        else None
    )
    return ReviewResult(
        stage_id=row.stage_id,
        version=row.version,
        status=row.status,
        score=row.score,
        latest=review_view(latest) if latest else None,
    )


def independent_company_reviewer(request, actor, material):
    if material.company_organization_id is not None:
        receipt = request.app.state.market_access.fetch(
            "employer",
            "affiliation",
            candidate_id=actor.subject,
            actor_id=actor.subject,
            organization_id=material.company_organization_id,
        )
        if receipt.allowed:
            raise HTTPException(403, "Independent company task review required")


def authorize(request, actor, stage_id):
    actor.require("assessment_reviewer", mfa=True)
    with Session(request.app.state.engine) as session:
        row = session.get(EvaluationIntake, str(stage_id))
        if row is None:
            raise HTTPException(404)
        if row.candidate_id == str(actor.subject):
            raise HTTPException(403)
        if row.status not in {"artifact_ready", "needs_evidence", "reviewed"}:
            raise HTTPException(409)
        if row.source is None:
            raise HTTPException(409, "Evidence collection is required before review")
        candidate_id, version = UUID(row.candidate_id), row.version
        material = PinnedMaterial.model_validate(row.material)
        source = source_model(row.source)
        refs = {
            key: UUID(getattr(row, key))
            for key in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
        }
    # Fetch live permissions/material outside the Evaluation transaction and locks.
    current = request.app.state.material_access.fetch(**refs)
    if current != material:
        raise HTTPException(503)
    independent_company_reviewer(request, actor, material)
    fresh_source = request.app.state.artifact_access.fetch(
        **refs,
        format=material.task.format,
        snapshot_version=material.snapshot_version,
        digest=material.snapshot_digest,
    )
    if fresh_source != source:
        raise HTTPException(503)
    return candidate_id, version


def guarded(request, actor, stage_id, candidate_id, authorized_version, session):
    for subject in sorted({str(actor.subject), str(candidate_id)}):
        subject_lock(session, subject)
    row = session.scalar(
        select(EvaluationIntake)
        .where(EvaluationIntake.stage_id == str(stage_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None or row.candidate_id != str(candidate_id):
        raise HTTPException(404)
    if row.version != authorized_version:
        raise HTTPException(409)
    request.app.state.processing_access.check(actor.subject)
    independent_company_reviewer(request, actor, PinnedMaterial.model_validate(row.material))
    request.app.state.processing_access.check_assessment(
        candidate_id, UUID(row.material["consent_id"])
    )
    if isinstance(source_model(row.source), PracticalSource):
        current = request.app.state.artifact_access.fetch(
            **{
                k: UUID(getattr(row, k))
                for k in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
            },
            format=row.material["task"]["format"],
            snapshot_version=row.material["snapshot_version"],
            digest=row.material["snapshot_digest"],
        )
        if current != source_model(row.source):
            raise HTTPException(409)
    return row


@router.get("/stages/{stage_id}", response_model=ReviewWorkspace)
def get_workspace(request: Request, actor: Actor, stage_id: UUID):
    candidate, version = authorize(request, actor, stage_id)
    with Session(request.app.state.engine) as session, session.begin():
        row = guarded(request, actor, stage_id, candidate, version, session)
        from reverse_hr.domains.evaluation_tests import TestEvidence, test_points
        from reverse_hr.event_transport import Signatures

        signatures = None
        if session.get(TestEvidence, row.stage_id):
            signatures = getattr(
                request.app.state, "evaluation_signatures", None
            ) or Signatures.from_settings(request.app.state.settings)
        points, proof_digest = test_points(session, row, signatures)
        return ReviewWorkspace(
            **result(session, row).model_dump(),
            material=row.material,
            source=row.source,
            trusted_test_points=points,
            test_proof_digest=proof_digest,
        )


@router.get("/stages/{stage_id}/history", response_model=list[ReviewView])
def history(
    request: Request,
    actor: Actor,
    stage_id: UUID,
    before: Annotated[int | None, Query(ge=1)] = None,
):
    candidate, version = authorize(request, actor, stage_id)
    with Session(request.app.state.engine) as session, session.begin():
        guarded(request, actor, stage_id, candidate, version, session)
        query = select(ReviewRecord).where(ReviewRecord.stage_id == str(stage_id))
        if before is not None:
            query = query.where(ReviewRecord.number < before)
        return [
            review_view(r)
            for r in session.scalars(query.order_by(ReviewRecord.number.desc()).limit(20))
        ]


def validate_decisions(row, body, test_scores=None, proof_digest=None):
    material = PinnedMaterial.model_validate(row.material)
    source = source_model(row.source)
    criteria = {c.key: c for c in material.task.rubric}
    if {d.criterion_key for d in body.decisions} != set(criteria):
        raise HTTPException(409)
    if source_digest(source) != material.snapshot_digest or (
        isinstance(source, PracticalSource)
        and (
            source.format != material.task.format
            or str(source.snapshot_id) != getattr(row, "snapshot_id", str(source.snapshot_id))
        )
    ):
        raise HTTPException(409)
    files = {f.path: f for f in source.files} if isinstance(source, FilesCommand) else {}
    for decision in body.decisions:
        criterion = criteria[decision.criterion_key]
        if decision.points is None:
            continue
        if decision.points > criterion.points:
            raise HTTPException(409)
        if criterion.evidence == "test_result":
            if (
                decision.citations
                or decision.recording_citations
                or decision.board_citations
                or decision.test_proof_digest != proof_digest
                or proof_digest is None
                or decision.points != (test_scores or {}).get(criterion.key)
            ):
                raise HTTPException(409)
            continue
        if decision.test_proof_digest is not None:
            raise HTTPException(409)
        if isinstance(source, FilesCommand):
            if (
                criterion.evidence != "artifact"
                or not decision.citations
                or decision.recording_citations
                or decision.board_citations
            ):
                raise HTTPException(409)
            for citation in decision.citations:
                file = files.get(citation.path)
                if (
                    file is None
                    or hashlib.sha256(file.content.encode()).hexdigest() != citation.file_digest
                    or citation.end_line > len(file.content.splitlines())
                ):
                    raise HTTPException(409)
        elif source.format == "whiteboard":
            if (
                criterion.evidence not in {"board_snapshot", "artifact"}
                or not decision.board_citations
                or decision.citations
                or decision.recording_citations
            ):
                raise HTTPException(409)
            shapes = {str(shape.id): shape for shape in source.board.state}
            for citation in decision.board_citations:
                shape = shapes.get(str(citation.object_id))
                if (
                    citation.snapshot_id != source.snapshot_id
                    or citation.snapshot_digest != source.digest
                    or shape is None
                    or sha(shape) != citation.object_digest
                ):
                    raise HTTPException(409)
        else:
            if (
                criterion.evidence not in {"timestamped_recording", "artifact"}
                or not decision.recording_citations
                or decision.citations
                or decision.board_citations
            ):
                raise HTTPException(409)
            segments = {segment.key: segment for segment in source.transcript.segments}
            for citation in decision.recording_citations:
                segment = segments.get(citation.segment_key)
                if (
                    citation.snapshot_id != source.snapshot_id
                    or citation.recording_digest != source.digest
                    or citation.transcript_id != source.transcript_id
                    or citation.transcript_digest != source.transcript_digest
                    or segment is None
                    or not segment.start_ms <= citation.start_ms < citation.end_ms <= segment.end_ms
                ):
                    raise HTTPException(409)
    return (
        sum(d.points for d in body.decisions)
        if all(d.points is not None for d in body.decisions)
        else None
    )


@router.post("/stages/{stage_id}/reviews", response_model=ReviewResult)
def record_review(
    request: Request,
    actor: Actor,
    stage_id: UUID,
    body: ReviewCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    candidate, authorized_version = authorize(request, actor, stage_id)
    expected = int(if_match.strip('"'))

    def guard(session):
        guarded(request, actor, stage_id, candidate, authorized_version, session)

    def change(session):
        row = session.get(EvaluationIntake, str(stage_id))
        if row.version != expected:
            raise HTTPException(409)
        from reverse_hr.domains.evaluation_tests import TestEvidence, test_points
        from reverse_hr.event_transport import Signatures

        signatures = None
        if session.get(TestEvidence, row.stage_id):
            signatures = getattr(
                request.app.state, "evaluation_signatures", None
            ) or Signatures.from_settings(request.app.state.settings)
        test_scores, proof_digest = test_points(session, row, signatures)
        if body.model_attempt_id is not None:
            from reverse_hr.evaluation_llm import ModelAttempt, attempt_input_digest

            attempt = session.get(ModelAttempt, str(body.model_attempt_id))
            if (
                attempt is None
                or attempt.stage_id != row.stage_id
                or attempt.candidate_id != row.candidate_id
                or attempt.status != "ready"
                or attempt.input_digest != attempt_input_digest(attempt, row.material, row.source)
            ):
                raise HTTPException(409, "Current model proposal required")
        score = validate_decisions(row, body, test_scores, proof_digest)
        row.version += 1
        row.review_number += 1
        row.status, row.score = ("reviewed" if score is not None else "needs_evidence"), score
        review = ReviewRecord(
            review_id=str(uuid4()),
            stage_id=row.stage_id,
            candidate_id=row.candidate_id,
            reviewer_id=str(actor.subject),
            model_attempt_id=str(body.model_attempt_id) if body.model_attempt_id else None,
            number=row.review_number,
            intake_version=row.version,
            decisions=body.model_dump(mode="json")["decisions"],
            score=score,
            reason=body.reason,
            created_at=datetime.now(UTC),
        )
        session.add(review)
        decisions = {d.criterion_key: d for d in body.decisions}
        material = PinnedMaterial.model_validate(row.material)
        row.requirements = [
            {
                "criterion_key": criterion.key,
                "competency": criterion.competency,
                "max_points": criterion.points,
                "evidence_type": criterion.evidence,
                "status": "reviewed" if decisions[criterion.key].points is not None else "pending",
                "points": decisions[criterion.key].points,
                "snapshot_id": row.snapshot_id,
                "digest": material.snapshot_digest,
                "test_proof_digest": decisions[criterion.key].test_proof_digest,
                "review_id": review.review_id
                if decisions[criterion.key].points is not None
                else None,
            }
            for criterion in material.task.rubric
        ]
        enqueue(
            session,
            EventEnvelope(
                event_type="evaluation.review_recorded.v1",
                producer="evaluation",
                correlation_id=request.state.trace_id,
                aggregate_id=stage_id,
                aggregate_version=row.version,
                payload={
                    "candidate_id": candidate,
                    "stage_id": stage_id,
                    "session_id": UUID(row.session_id),
                    "review_id": UUID(review.review_id),
                    "reviewer_id": actor.subject,
                },
            ),
        )
        return result(session, row).model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"evaluation_review:{stage_id}",
        idempotency,
        {"version": expected, "body": body.model_dump(mode="json")},
        change,
        guard=guard,
        present=lambda session, _: result(
            session, session.get(EvaluationIntake, str(stage_id))
        ).model_dump(mode="json"),
    )
