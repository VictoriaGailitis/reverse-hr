"""Minimal signed human decisions for the Candidate projection."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.contracts import Contract, Grade
from reverse_hr.evaluation_artifact_access import bound
from reverse_hr.processing_access import (
    ProcessingAccess,
    ProcessingRequest,
    canonical,
    sign,
    verify,
)
from reverse_hr.qualification_contracts import QualificationEvidence

REQUEST = b"reverse-hr.confirmed-grade-request.v1\0"
RESPONSE = b"reverse-hr.confirmed-grade-response.v1\0"


class DecisionRequest(ProcessingRequest):
    requester: Literal["candidate"] = "candidate"
    purpose: Literal["confirmed-grade"] = "confirmed-grade"
    session_id: UUID
    decision_id: UUID
    reviewer_id: UUID
    session_version: int = Field(strict=True, ge=1)


class DecisionSummary(Contract):
    specialization: str = Field(min_length=1, max_length=100)
    target_grade: Grade
    status: Literal["confirmed", "rejected", "technical_failure"]
    decided_at: datetime
    decision_revision: int = Field(default=1, strict=True, ge=1, le=2)
    supersedes_decision_id: UUID | None = None
    demo: Literal[True] = True
    qualification: QualificationEvidence | None = None

    @model_validator(mode="after")
    def aware(self):
        if (self.decision_revision == 1) != (self.supersedes_decision_id is None):
            raise ValueError("Invalid decision revision chain")
        if self.decided_at.tzinfo is None or self.decided_at > datetime.now(UTC):
            raise ValueError("Invalid decision time")
        return self


class DecisionReceipt(DecisionRequest):
    allowed: bool = Field(strict=True)
    decision: DecisionSummary | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.allowed != (self.decision is not None):
            raise ValueError("Invalid decision receipt")
        return self


class ConfirmedGradeAccess(ProcessingAccess):
    def fetch(self, **refs):
        body = DecisionRequest(**refs, nonce=uuid4(), issued_at=datetime.now(UTC))
        try:
            raw, signature = self._send(
                "confirmed-grade",
                canonical(body),
                sign(self.signatures, REQUEST, body),
                origin=self.settings.assessment_api_url,
                max_bytes=32768,
            )
            if len(raw) > 32768:
                raise ValueError("Oversized decision receipt")
            receipt = DecisionReceipt.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, RESPONSE, receipt)
            if raw != canonical(receipt) or not bound(body, receipt):
                raise ValueError("Unbound decision receipt")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt.decision
