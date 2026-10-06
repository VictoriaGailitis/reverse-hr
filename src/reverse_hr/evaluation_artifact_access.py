"""Purpose-bound retrieval of a submitted artifact; never a code execution permit."""

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.domains.coding_workspace import FilesCommand
from reverse_hr.evaluation_access import MaterialRequest
from reverse_hr.processing_access import ProcessingAccess, canonical, fresh, sign, verify

ARTIFACT_REQUEST = b"reverse-hr.evaluation-artifact-request.v1\0"
ARTIFACT_RESPONSE = b"reverse-hr.evaluation-artifact-response.v1\0"
PERMIT_REQUEST = b"reverse-hr.evaluation-artifact-permit-request.v1\0"
PERMIT_RESPONSE = b"reverse-hr.evaluation-artifact-permit-response.v1\0"
MAX_ARTIFACT_BYTES = 2 * 1024 * 1024


class ArtifactRequest(MaterialRequest):
    purpose: Literal["rubric-evidence"] = "rubric-evidence"
    format: Literal["code", "sql"]
    snapshot_version: int = Field(strict=True, ge=1)
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class ArtifactReceipt(ArtifactRequest):
    allowed: bool = Field(strict=True)
    manifest: FilesCommand | None = None

    @model_validator(mode="after")
    def complete(self):
        if self.allowed != (self.manifest is not None):
            raise ValueError("Invalid artifact receipt")
        if self.allowed and (
            [f.path for f in self.manifest.files] != sorted(f.path for f in self.manifest.files)
            or hashlib.sha256(canonical(self.manifest)).hexdigest() != self.digest
        ):
            raise ValueError("Invalid artifact digest")
        return self


class ArtifactPermitRequest(ArtifactRequest):
    requester: Literal["coding-workspace"]


class ArtifactPermit(ArtifactPermitRequest):
    allowed: bool = Field(strict=True)


def bound(request, response):
    return fresh(response.issued_at) and all(
        getattr(request, key) == getattr(response, key)
        for key in type(request).model_fields
        if key != "issued_at"
    )


class ArtifactAccess(ProcessingAccess):
    def send_artifact(self, body, signature):
        return self._send(
            "evaluation-artifact",
            body,
            signature,
            origin=self.settings.workspace_api_url,
            max_bytes=MAX_ARTIFACT_BYTES,
        )

    def fetch(
        self,
        *,
        candidate_id,
        session_id,
        stage_id,
        workspace_id,
        snapshot_id,
        format,
        snapshot_version,
        digest,
    ):
        body = ArtifactRequest(
            candidate_id=candidate_id,
            session_id=session_id,
            stage_id=stage_id,
            workspace_id=workspace_id,
            snapshot_id=snapshot_id,
            format=format,
            snapshot_version=snapshot_version,
            digest=digest,
            requester="evaluation",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_artifact(
                canonical(body), sign(self.signatures, ARTIFACT_REQUEST, body)
            )
            if len(raw) > MAX_ARTIFACT_BYTES:
                raise ValueError("Oversized artifact")
            receipt = ArtifactReceipt.model_validate_json(raw)
            verify(self.signatures, "coding-workspace", signature, ARTIFACT_RESPONSE, receipt)
            if raw != canonical(receipt) or not bound(body, receipt):
                raise ValueError("Invalid artifact binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt.manifest


class ArtifactPermitAccess(ProcessingAccess):
    def send_permit(self, body, signature):
        return self._send(
            "evaluation-artifact-admission",
            body,
            signature,
            origin=self.settings.assessment_api_url,
        )

    def check(self, body: ArtifactRequest):
        request = ArtifactPermitRequest(
            **(
                body.model_dump()
                | {
                    "requester": "coding-workspace",
                    "nonce": uuid4(),
                    "issued_at": datetime.now(UTC),
                }
            )
        )
        try:
            raw, signature = self.send_permit(
                canonical(request), sign(self.signatures, PERMIT_REQUEST, request)
            )
            if len(raw) > 4096:
                raise ValueError("Oversized permit")
            status = ArtifactPermit.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, PERMIT_RESPONSE, status)
            if raw != canonical(status) or not bound(request, status):
                raise ValueError("Invalid permit binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not status.allowed:
            raise HTTPException(409)
        return status
