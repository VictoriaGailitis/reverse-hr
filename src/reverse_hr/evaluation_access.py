"""Signed, bounded retrieval of pinned Assessment material for Evaluation only."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.contracts import Contract
from reverse_hr.domains.assessment import Competency, Task
from reverse_hr.processing_access import (
    ProcessingAccess,
    ProcessingRequest,
    canonical,
    fresh,
    sign,
    verify,
)
from reverse_hr.session_test_pins import SessionSuitePin

MATERIAL_REQUEST = b"reverse-hr.evaluation-material-request.v1\0"
MATERIAL_RESPONSE = b"reverse-hr.evaluation-material-response.v1\0"
MAX_MATERIAL_BYTES = 278528


class MaterialRequest(ProcessingRequest):
    requester: Literal["evaluation"]
    session_id: UUID
    stage_id: UUID
    workspace_id: UUID
    snapshot_id: UUID


class PinnedMaterial(Contract):
    consent_id: UUID
    plan_version_id: UUID
    revision_id: UUID
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    task: Task
    competencies: list[Competency] = Field(min_length=1, max_length=20)
    snapshot_version: int = Field(ge=1, strict=True)
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    test_suite: SessionSuitePin | None = None
    demo: Literal[True] = True

    @model_validator(mode="after")
    def consistent(self):
        keys = [item.key for item in self.competencies]
        if (
            self.task.format not in {"code", "sql"}
            or len(set(keys)) != len(keys)
            or set(keys) != {item.competency for item in self.task.rubric}
            or (
                self.test_suite is not None
                and (
                    self.test_suite.revision_id != self.revision_id
                    or self.test_suite.pin.content_digest != self.content_digest
                    or self.test_suite.task_key != self.task.key
                    or not any(c.evidence == "test_result" for c in self.task.rubric)
                )
            )
        ):
            raise ValueError("Invalid practical material")
        return self


class MaterialReceipt(MaterialRequest):
    allowed: bool = Field(strict=True)
    material: PinnedMaterial | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.allowed != (self.material is not None):
            raise ValueError("Invalid material receipt")
        if (
            self.material is not None
            and self.material.test_suite is not None
            and self.material.test_suite.stage_id != self.stage_id
        ):
            raise ValueError("Test suite belongs to another stage")
        return self


class MaterialAccess(ProcessingAccess):
    def send_material(self, body, signature):
        return self._send(
            "evaluation-material",
            body,
            signature,
            origin=self.settings.assessment_api_url,
            max_bytes=MAX_MATERIAL_BYTES,
        )

    def fetch(self, candidate_id, session_id, stage_id, workspace_id, snapshot_id):
        body = MaterialRequest(
            candidate_id=candidate_id,
            session_id=session_id,
            stage_id=stage_id,
            workspace_id=workspace_id,
            snapshot_id=snapshot_id,
            requester="evaluation",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_material(
                canonical(body), sign(self.signatures, MATERIAL_REQUEST, body)
            )
            if len(raw) > MAX_MATERIAL_BYTES:
                raise ValueError("Oversized material")
            receipt = MaterialReceipt.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, MATERIAL_RESPONSE, receipt)
            if (
                raw != canonical(receipt)
                or not fresh(receipt.issued_at)
                or any(
                    getattr(body, key) != getattr(receipt, key)
                    for key in (
                        "candidate_id",
                        "session_id",
                        "stage_id",
                        "workspace_id",
                        "snapshot_id",
                        "nonce",
                        "requester",
                    )
                )
            ):
                raise ValueError("Invalid material binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt.material
