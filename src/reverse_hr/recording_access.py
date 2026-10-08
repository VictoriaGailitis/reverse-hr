"""Fresh recording consent, distinct from the assessment consent."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field

from reverse_hr.processing_access import (
    ProcessingAccess,
    ProcessingRequest,
    canonical,
    fresh,
    sign,
    verify,
)

REQUEST = b"reverse-hr.recording-permission-request.v1\0"
RESPONSE = b"reverse-hr.recording-permission-response.v1\0"


class RecordingRequest(ProcessingRequest):
    requester: Literal["media"]
    consent_id: UUID


class RecordingStatus(RecordingRequest):
    allowed: bool = Field(strict=True)


class RecordingAccess(ProcessingAccess):
    def check_recording(self, subject, consent):
        body = RecordingRequest(
            candidate_id=subject,
            consent_id=consent,
            requester="media",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self._send(
                "recording-permission", canonical(body), sign(self.signatures, REQUEST, body)
            )
            status = RecordingStatus.model_validate_json(raw)
            verify(self.signatures, "privacy", signature, RESPONSE, status)
            if (
                len(raw) > 4096
                or raw != canonical(status)
                or not fresh(status.issued_at)
                or any(
                    getattr(body, key) != getattr(status, key)
                    for key in type(body).model_fields
                    if key != "issued_at"
                )
            ):
                raise ValueError("Invalid recording consent binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not status.allowed:
            raise HTTPException(409)
