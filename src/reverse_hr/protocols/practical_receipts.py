"""Metadata-only receipts for immutable recordings and board snapshots."""

from datetime import UTC, datetime
from uuid import uuid4

from fastapi import HTTPException

from reverse_hr.protocols.snapshot_access import (
    SNAPSHOT_REQUEST,
    SNAPSHOT_RESPONSE,
    SnapshotAccess,
    SnapshotReceipt,
    SnapshotRequest,
)
from reverse_hr.shared.signing import canonical, fresh, sign, verify


class PracticalReceiptAccess(SnapshotAccess):
    def fetch(self, candidate_id, session_id, stage_id, workspace_id, snapshot_id, *, format):
        producer = "whiteboard" if format == "whiteboard" else "media"
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
            raw, signature = self._send(
                "practical-receipt",
                canonical(body),
                sign(self.signatures, SNAPSHOT_REQUEST, body),
                origin=getattr(self.settings, producer + "_api_url"),
            )
            receipt = SnapshotReceipt.model_validate_json(raw)
            verify(self.signatures, producer, signature, SNAPSHOT_RESPONSE, receipt)
            if (
                len(raw) > 4096
                or raw != canonical(receipt)
                or not fresh(receipt.issued_at)
                or any(
                    getattr(body, key) != getattr(receipt, key)
                    for key in type(body).model_fields
                    if key != "issued_at"
                )
                or (receipt.allowed and receipt.format != format)
            ):
                raise ValueError("Invalid practical receipt binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt
