"""Purpose-bound immutable snapshot receipt; source text is never returned."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field, model_validator

from reverse_hr.processing_access import (
    MAX_BYTES,
    ProcessingAccess,
    ProcessingRequest,
    canonical,
    fresh,
    sign,
    verify,
)

SNAPSHOT_REQUEST = b"reverse-hr.snapshot-receipt-request.v1\0"
SNAPSHOT_RESPONSE = b"reverse-hr.snapshot-receipt-response.v1\0"


class SnapshotRequest(ProcessingRequest):
    requester: Literal["assessment"]
    session_id: UUID
    stage_id: UUID
    workspace_id: UUID
    snapshot_id: UUID


class SnapshotReceipt(SnapshotRequest):
    allowed: bool = Field(strict=True)
    format: Literal["code", "sql"] | None = None
    snapshot_version: int | None = Field(default=None, ge=1, strict=True)
    digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def complete(self):
        values = (self.format, self.snapshot_version, self.digest)
        if (self.allowed and any(v is None for v in values)) or (
            not self.allowed and any(v is not None for v in values)
        ):
            raise ValueError("Invalid receipt")
        return self


class SnapshotAccess(ProcessingAccess):
    def send_receipt(self, body, signature):
        return self._send(
            "snapshot-receipt", body, signature, origin=self.settings.workspace_api_url
        )

    def fetch(self, candidate_id, session_id, stage_id, workspace_id, snapshot_id):
        body = SnapshotRequest(
            candidate_id=candidate_id,
            session_id=session_id,
            stage_id=stage_id,
            workspace_id=workspace_id,
            snapshot_id=snapshot_id,
            requester="assessment",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_receipt(
                canonical(body), sign(self.signatures, SNAPSHOT_REQUEST, body)
            )
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized receipt")
            receipt = SnapshotReceipt.model_validate_json(raw)
            verify(self.signatures, "coding-workspace", signature, SNAPSHOT_RESPONSE, receipt)
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
                        "requester",
                        "nonce",
                    )
                )
            ):
                raise ValueError("Invalid receipt binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt
