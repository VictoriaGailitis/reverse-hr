"""Purpose-bound retrieval of the exact immutable snapshot requested for a run."""

import hashlib
from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.contracts.workspace import FilesCommand
from reverse_hr.protocols.processing_access import ProcessingAccess, ProcessingRequest
from reverse_hr.shared.signing import canonical, fresh, sign, verify

MANIFEST_REQUEST = b"reverse-hr.run-manifest-request.v1\0"
MANIFEST_RESPONSE = b"reverse-hr.run-manifest-response.v1\0"
MAX_MANIFEST_BYTES = 2 * 1024 * 1024


class ManifestRequest(ProcessingRequest):
    requester: Literal["code-runner"]
    purpose: Literal["write", "read"] = "write"
    run_id: UUID
    workspace_id: UUID
    snapshot_id: UUID


class ManifestStatus(ManifestRequest):
    allowed: bool = Field(strict=True)
    snapshot_version: int | None = Field(default=None, strict=True, ge=1)
    format: Literal["code", "sql"] | None = None
    digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    manifest: FilesCommand | None = None

    @model_validator(mode="after")
    def complete(self):
        values = (self.snapshot_version, self.format, self.digest, self.manifest)
        if (self.allowed and any(v is None for v in values)) or (
            not self.allowed and any(v is not None for v in values)
        ):
            raise ValueError("Incomplete manifest binding")
        if self.allowed:
            paths = [f.path for f in self.manifest.files]
            if (
                paths != sorted(paths)
                or hashlib.sha256(canonical(self.manifest)).hexdigest() != self.digest
            ):
                raise ValueError("Invalid snapshot digest")
        return self


class ManifestAccess(ProcessingAccess):
    def send_manifest(self, body, signature):
        return self._send(
            "run-manifest",
            body,
            signature,
            origin=self.settings.workspace_api_url,
            max_bytes=MAX_MANIFEST_BYTES,
        )

    def fetch(self, candidate_id, run_id, workspace_id, snapshot_id, purpose="write"):
        body = ManifestRequest(
            candidate_id=candidate_id,
            purpose=purpose,
            run_id=run_id,
            workspace_id=workspace_id,
            snapshot_id=snapshot_id,
            requester="code-runner",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_manifest(
                canonical(body), sign(self.signatures, MANIFEST_REQUEST, body)
            )
            if len(raw) > MAX_MANIFEST_BYTES:
                raise ValueError("Oversized manifest")
            result = ManifestStatus.model_validate_json(raw)
            verify(self.signatures, "coding-workspace", signature, MANIFEST_RESPONSE, result)
            if (
                raw != canonical(result)
                or not fresh(result.issued_at)
                or any(
                    getattr(result, key) != getattr(body, key)
                    for key in (
                        "candidate_id",
                        "run_id",
                        "workspace_id",
                        "snapshot_id",
                        "requester",
                        "purpose",
                        "nonce",
                    )
                )
            ):
                raise ValueError("Invalid binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        return result if result.allowed else None
