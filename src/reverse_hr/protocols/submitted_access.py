"""Fresh purpose-bound permission and immutable inputs for submitted hidden tests."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.session_test_pins import SessionSuitePin
from reverse_hr.contracts.test_suites import SuiteDefinition, digest
from reverse_hr.contracts.workspace import FilesCommand
from reverse_hr.protocols.evaluation_artifact_access import bound
from reverse_hr.protocols.processing_access import ProcessingAccess, ProcessingRequest
from reverse_hr.shared.signing import canonical, sign, verify

REQUEST = b"reverse-hr.submitted-tests-request.v1\0"
RESPONSE = b"reverse-hr.submitted-tests-response.v1\0"
SOURCE_REQUEST = b"reverse-hr.submitted-tests-source-request.v1\0"
SOURCE_RESPONSE = b"reverse-hr.submitted-tests-source-response.v1\0"
MAX_BYTES = 2105344


class SubmittedRequest(ProcessingRequest):
    requester: Literal["code-runner", "coding-workspace"]
    purpose: Literal["submitted-tests"] = "submitted-tests"
    session_id: UUID
    stage_id: UUID
    workspace_id: UUID
    snapshot_id: UUID
    node_id: UUID
    runtime_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")


class SubmittedMaterial(Contract):
    consent_id: UUID
    snapshot_version: int = Field(strict=True, ge=1)
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding: SessionSuitePin
    definition: SuiteDefinition

    @model_validator(mode="after")
    def consistent(self):
        if digest(self.definition) != self.binding.pin.definition_digest:
            raise ValueError("Private suite digest mismatch")
        return self


class SubmittedReceipt(SubmittedRequest):
    allowed: bool = Field(strict=True)
    material: SubmittedMaterial | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.allowed != (self.material is not None):
            raise ValueError("Invalid submitted material")
        if self.material is not None and (
            self.material.binding.stage_id != self.stage_id
            or self.material.binding.node_id != self.node_id
            or self.material.binding.pin.runtime_fingerprint != self.runtime_fingerprint
        ):
            raise ValueError("Foreign submitted material")
        return self


class SubmittedSourceRequest(SubmittedRequest):
    requester: Literal["code-runner"]
    purpose: Literal["submitted-tests-source"] = "submitted-tests-source"
    snapshot_version: int = Field(strict=True, ge=1)
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    binding: SessionSuitePin

    @model_validator(mode="after")
    def consistent(self):
        if (
            self.binding.stage_id != self.stage_id
            or self.binding.node_id != self.node_id
            or self.binding.pin.runtime_fingerprint != self.runtime_fingerprint
        ):
            raise ValueError("Foreign source binding")
        return self


class SubmittedSourceReceipt(SubmittedSourceRequest):
    allowed: bool = Field(strict=True)
    manifest: FilesCommand | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.allowed != (self.manifest is not None):
            raise ValueError("Invalid submitted source")
        if self.manifest is not None and (
            digest(self.manifest) != self.snapshot_digest
            or self.manifest.files != sorted(self.manifest.files, key=lambda f: f.path)
        ):
            raise ValueError("Source digest mismatch")
        return self


class SubmittedAccess(ProcessingAccess):
    def exchange(self, route, body, request_context, response_context, model, origin):
        try:
            raw, signature = self._send(
                route,
                canonical(body),
                sign(self.signatures, request_context, body),
                origin=origin,
                max_bytes=MAX_BYTES,
            )
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized submitted response")
            receipt = model.model_validate_json(raw)
            verify(
                self.signatures,
                "assessment" if model is SubmittedReceipt else "coding-workspace",
                signature,
                response_context,
                receipt,
            )
            if raw != canonical(receipt) or not bound(body, receipt):
                raise ValueError("Unbound submitted response")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt

    def fetch(self, **refs):
        body = SubmittedRequest(
            **refs, requester=self.settings.service_name, nonce=uuid4(), issued_at=datetime.now(UTC)
        )
        return self.exchange(
            "submitted-tests",
            body,
            REQUEST,
            RESPONSE,
            SubmittedReceipt,
            self.settings.assessment_api_url,
        ).material

    def source(self, material, **refs):
        body = SubmittedSourceRequest(
            **refs,
            requester="code-runner",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
            snapshot_version=material.snapshot_version,
            snapshot_digest=material.snapshot_digest,
            binding=material.binding,
        )
        return self.exchange(
            "submitted-tests-source",
            body,
            SOURCE_REQUEST,
            SOURCE_RESPONSE,
            SubmittedSourceReceipt,
            self.settings.workspace_api_url,
        ).manifest
