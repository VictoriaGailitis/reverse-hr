"""Signed host-comparison evidence, bound to the submitted source and pinned suite."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import Field, model_validator

from reverse_hr.contracts import Contract
from reverse_hr.processing_access import ProcessingRequest
from reverse_hr.runner_readiness import ProbeRecord
from reverse_hr.session_test_pins import SessionSuitePin

PROOF = b"reverse-hr.submitted-test-proof.v1\0"
DELIVERY = b"reverse-hr.submitted-test-delivery.v1\0"
RECEIPT = b"reverse-hr.submitted-test-receipt.v1\0"


class TestOutcome(Contract):
    case_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    criterion_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    attempt_id: UUID
    input_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    case_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    capture_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    verdict: Literal["passed", "failed", "inconclusive"]


class TestProof(Contract):
    producer: Literal["code-runner"] = "code-runner"
    purpose: Literal["submitted-test-result"] = "submitted-test-result"
    candidate_id: UUID
    session_id: UUID
    stage_id: UUID
    workspace_id: UUID
    snapshot_id: UUID
    snapshot_version: int = Field(strict=True, ge=1)
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding: SessionSuitePin
    probe: ProbeRecord
    completed_at: datetime
    outcomes: list[TestOutcome] = Field(min_length=1, max_length=20)
    demo: Literal[True] = True

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.binding.stage_id != self.stage_id
            or self.binding.node_id != self.probe.node_id
            or self.binding.pin.runtime_fingerprint != self.probe.fingerprint
            or self.completed_at.tzinfo is None
            or self.probe.checked_at.tzinfo is None
            or self.probe.checked_at > self.completed_at
            or self.completed_at > datetime.now(UTC)
            or len({o.case_key for o in self.outcomes}) != len(self.outcomes)
            or len({o.attempt_id for o in self.outcomes}) != len(self.outcomes)
        ):
            raise ValueError("Inconsistent submitted proof")
        return self


class ResultDelivery(ProcessingRequest):
    requester: Literal["code-runner"] = "code-runner"
    purpose: Literal["submitted-test-delivery"] = "submitted-test-delivery"
    proof: TestProof
    proof_signature: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def bound(self):
        if self.candidate_id != self.proof.candidate_id:
            raise ValueError("Foreign test result")
        return self


class ResultReceipt(ProcessingRequest):
    requester: Literal["code-runner"] = "code-runner"
    purpose: Literal["submitted-test-delivery"] = "submitted-test-delivery"
    stage_id: UUID
    proof_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    allowed: bool = Field(strict=True)


def delivery_body(proof, signature):
    return ResultDelivery(
        candidate_id=proof.candidate_id,
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
        proof=proof,
        proof_signature=signature,
    )
