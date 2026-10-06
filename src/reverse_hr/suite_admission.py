"""Fresh Assessment permission to validate a reviewed demo suite, never to grade."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.processing_access import (
    ProcessingAccess,
    ProcessingRequest,
    canonical,
    fresh,
    sign,
    verify,
)
from reverse_hr.test_harness import SuitePin, ValidationPlan
from reverse_hr.test_suites import SuiteDefinition, digest

SUITE_REQUEST = b"reverse-hr.suite-validation-admission-request.v1\0"
SUITE_RESPONSE = b"reverse-hr.suite-validation-admission-response.v1\0"
MAX_BYTES = 4096
MATERIAL_REQUEST = b"reverse-hr.suite-validation-material-request.v1\0"
MATERIAL_RESPONSE = b"reverse-hr.suite-validation-material-response.v1\0"
MAX_MATERIAL_BYTES = 2097152 + 4096


class SuiteAdmissionRequest(ProcessingRequest):
    requester: Literal["code-runner"]
    purpose: Literal["suite-validation"]
    validation_id: UUID
    pin: SuitePin
    plan_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class SuitePermit(SuiteAdmissionRequest):
    allowed: bool = Field(strict=True)


class SuiteMaterialRequest(SuiteAdmissionRequest):
    purpose: Literal["suite-validation-material"]


class SuiteMaterial(SuiteMaterialRequest):
    allowed: bool = Field(strict=True)
    definition: SuiteDefinition | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.allowed != (self.definition is not None):
            raise ValueError("Invalid suite material response")
        if self.definition is not None and digest(self.definition) != self.pin.definition_digest:
            raise ValueError("Definition digest mismatch")
        return self


class SuiteAdmissionAccess(ProcessingAccess):
    def send_material(self, body, signature):
        return self._send(
            "suite-validation-material",
            body,
            signature,
            origin=self.settings.assessment_api_url,
            max_bytes=MAX_MATERIAL_BYTES,
        )

    def fetch(self, owner_id, plan: ValidationPlan):
        if self.settings.service_name != "code-runner":
            raise HTTPException(503)
        plan = ValidationPlan.model_validate(plan.model_dump(mode="json"))
        body = SuiteMaterialRequest(
            candidate_id=owner_id,
            requester="code-runner",
            purpose="suite-validation-material",
            validation_id=plan.validation_id,
            pin=plan.pin,
            plan_digest=digest(plan),
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_material(
                canonical(body), sign(self.signatures, MATERIAL_REQUEST, body)
            )
            if len(raw) > MAX_MATERIAL_BYTES:
                raise ValueError("Oversized suite material")
            receipt = SuiteMaterial.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, MATERIAL_RESPONSE, receipt)
            if (
                raw != canonical(receipt)
                or not fresh(receipt.issued_at)
                or any(
                    getattr(body, key) != getattr(receipt, key)
                    for key in SuiteMaterialRequest.model_fields
                    if key != "issued_at"
                )
            ):
                raise ValueError("Invalid suite material binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        from reverse_hr.test_harness import build_plan

        if build_plan(receipt.definition, plan.pin, plan.validation_id) != plan:
            raise HTTPException(503)
        return receipt.definition

    def send_permit(self, body, signature):
        return self._send(
            "suite-validation-admission",
            body,
            signature,
            origin=self.settings.assessment_api_url,
            max_bytes=MAX_BYTES,
        )

    def check(self, owner_id, plan: ValidationPlan):
        if self.settings.service_name != "code-runner":
            raise HTTPException(503)
        plan = ValidationPlan.model_validate(plan.model_dump(mode="json"))
        body = SuiteAdmissionRequest(
            candidate_id=owner_id,
            requester="code-runner",
            purpose="suite-validation",
            validation_id=plan.validation_id,
            pin=plan.pin,
            plan_digest=digest(plan),
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_permit(
                canonical(body), sign(self.signatures, SUITE_REQUEST, body)
            )
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized suite permit")
            receipt = SuitePermit.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, SUITE_RESPONSE, receipt)
            if (
                raw != canonical(receipt)
                or not fresh(receipt.issued_at)
                or any(
                    getattr(body, key) != getattr(receipt, key)
                    for key in SuiteAdmissionRequest.model_fields
                    if key != "issued_at"
                )
            ):
                raise ValueError("Invalid suite permit binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
