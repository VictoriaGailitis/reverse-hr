"""Fresh signed delivery of a suite verdict; receipt does not enable scoring."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.contracts.runtime_trust import RuntimeAttestation
from reverse_hr.contracts.suite_verdict import SuiteVerdict
from reverse_hr.contracts.test_suites import digest
from reverse_hr.protocols.processing_access import ProcessingAccess, ProcessingRequest
from reverse_hr.shared.signing import canonical, fresh, sign, verify

INTAKE_REQUEST = b"reverse-hr.suite-verdict-intake-request.v1\0"
INTAKE_RESPONSE = b"reverse-hr.suite-verdict-intake-response.v1\0"
MAX_BYTES = 4096


class VerdictDelivery(ProcessingRequest):
    requester: Literal["code-runner"]
    purpose: Literal["suite-verdict-intake"]
    proof: SuiteVerdict
    proof_signature: str = Field(min_length=1, max_length=128)
    attestation: RuntimeAttestation | None = None
    attestation_signature: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def bound(self):
        if self.candidate_id != self.proof.owner_id:
            raise ValueError("Verdict owner mismatch")
        if (self.attestation is None) != (self.attestation_signature is None):
            raise ValueError("Attestation requires its signature")
        return self


class VerdictReceipt(ProcessingRequest):
    requester: Literal["code-runner"]
    purpose: Literal["suite-verdict-intake"]
    validation_id: UUID
    proof_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    attestation_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    allowed: bool = Field(strict=True)
    verdict: Literal["accepted", "rejected"] | None = None
    runtime_validated: Literal[False] = False
    scoring_enabled: Literal[False] = False

    @model_validator(mode="after")
    def complete(self):
        if self.allowed != (self.verdict is not None):
            raise ValueError("Invalid verdict receipt")
        return self


class VerdictDeliveryAccess(ProcessingAccess):
    def send_verdict(self, body, signature):
        return self._send(
            "suite-validation-verdict",
            body,
            signature,
            origin=self.settings.assessment_api_url,
            max_bytes=MAX_BYTES,
        )

    def deliver(
        self,
        proof: SuiteVerdict,
        proof_signature: str,
        *,
        attestation=None,
        attestation_signature=None,
    ):
        if self.settings.service_name != "code-runner":
            raise HTTPException(503)
        body = VerdictDelivery(
            candidate_id=proof.owner_id,
            requester="code-runner",
            purpose="suite-verdict-intake",
            proof=proof,
            proof_signature=proof_signature,
            attestation=attestation,
            attestation_signature=attestation_signature,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_verdict(
                canonical(body), sign(self.signatures, INTAKE_REQUEST, body)
            )
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized verdict receipt")
            receipt = VerdictReceipt.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, INTAKE_RESPONSE, receipt)
            if raw != canonical(receipt) or not fresh(receipt.issued_at):
                raise ValueError("Invalid verdict response")
            if (
                any(
                    getattr(body, key) != getattr(receipt, key)
                    for key in ("candidate_id", "nonce", "requester", "purpose")
                )
                or receipt.validation_id != proof.validation_id
                or receipt.proof_digest != digest(proof)
                or receipt.attestation_digest != (digest(attestation) if attestation else None)
            ):
                raise ValueError("Invalid verdict receipt binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        if receipt.verdict != proof.verdict:
            raise HTTPException(503)
        return receipt
