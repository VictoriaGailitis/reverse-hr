"""Fresh signed stage scores for Assessment; immutable review references stay pinned."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract
from reverse_hr.protocols.evaluation_artifact_access import bound
from reverse_hr.protocols.processing_access import ProcessingAccess, ProcessingRequest
from reverse_hr.shared.signing import canonical, sign, verify

REQUEST = b"reverse-hr.stage-score-request.v1\0"
RESPONSE = b"reverse-hr.stage-score-response.v1\0"


class ScoreRequest(ProcessingRequest):
    requester: Literal["assessment"] = "assessment"
    purpose: Literal["session-score"] = "session-score"
    session_id: UUID
    stage_id: UUID
    workspace_id: UUID
    snapshot_id: UUID


class CriterionScore(Contract):
    criterion_key: str
    competency: str
    max_points: int = Field(strict=True, ge=1, le=100)
    points: int | None = Field(default=None, strict=True, ge=0, le=100)
    evidence_type: Literal["artifact", "test_result", "timestamped_recording", "board_snapshot"]

    @model_validator(mode="after")
    def bounded(self):
        if self.points is not None and self.points > self.max_points:
            raise ValueError("Criterion score exceeds rubric")
        return self


class StageScore(Contract):
    additional_verification_required: bool = Field(
        default=False, strict=True, exclude_if=lambda value: not value
    )
    origin: Literal["human", "automatic"] = Field(
        default="human", exclude_if=lambda value: value == "human"
    )
    model_attempt_id: UUID | None = None
    llm_model: str | None = Field(default=None, min_length=1, max_length=200)
    llm_prompt_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    snapshot_version: int = Field(strict=True, ge=1)
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    revision_id: UUID
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    task_key: str
    review_id: UUID | None
    reviewer_id: UUID | None
    criteria: list[CriterionScore] = Field(min_length=1, max_length=20)
    score: int | None = Field(default=None, strict=True, ge=0, le=100)
    evidence_digest: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def coherent(self):
        if (
            len(
                {
                    self.model_attempt_id is None,
                    self.llm_model is None,
                    self.llm_prompt_digest is None,
                }
            )
            != 1
        ):
            raise ValueError("Incomplete model provenance")
        if (
            len({c.criterion_key for c in self.criteria}) != len(self.criteria)
            or sum(c.max_points for c in self.criteria) != 100
        ):
            raise ValueError("Invalid stage rubric")
        expected = (
            sum(c.points for c in self.criteria)
            if all(c.points is not None for c in self.criteria) and self.review_id is not None
            else None
        )
        if self.score != expected or (self.review_id is None) != (self.reviewer_id is None):
            raise ValueError("Incomplete stage score")
        return self


class ScoreReceipt(ScoreRequest):
    allowed: bool = Field(strict=True)
    stage: StageScore | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.allowed != (self.stage is not None):
            raise ValueError("Invalid stage receipt")
        return self


class GradeAccess(ProcessingAccess):
    def fetch(self, **refs):
        body = ScoreRequest(**refs, nonce=uuid4(), issued_at=datetime.now(UTC))
        try:
            raw, signature = self._send(
                "stage-score",
                canonical(body),
                sign(self.signatures, REQUEST, body),
                origin=self.settings.evaluation_api_url,
                max_bytes=16384,
            )
            if len(raw) > 16384:
                raise ValueError("Oversized stage score")
            receipt = ScoreReceipt.model_validate_json(raw)
            verify(self.signatures, "evaluation", signature, RESPONSE, receipt)
            if raw != canonical(receipt) or not bound(body, receipt):
                raise ValueError("Unbound score receipt")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt.stage
