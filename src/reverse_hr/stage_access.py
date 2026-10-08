"""Signed Assessment authorization for reading or writing a candidate's code/SQL stage."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field

from reverse_hr.processing_access import (
    MAX_BYTES,
    ProcessingAccess,
    ProcessingRequest,
    canonical,
    fresh,
    sign,
    verify,
)

STAGE_REQUEST_CONTEXT = b"reverse-hr.workspace-stage-request.v1\0"
STAGE_RESPONSE_CONTEXT = b"reverse-hr.workspace-stage-response.v1\0"


class StageRequest(ProcessingRequest):
    requester: Literal["coding-workspace", "media", "whiteboard", "proctoring"]
    purpose: Literal["write", "read"] = "write"
    session_id: UUID
    stage_id: UUID


class StageStatus(StageRequest):
    allowed: bool = Field(strict=True)
    format: Literal["code", "sql", "voice", "vcv", "whiteboard"] | None


class StageAccess(ProcessingAccess):
    def send_stage(self, body, signature):
        return self._send(
            "workspace-stage", body, signature, origin=self.settings.assessment_api_url
        )

    def check_stage(self, subject, session_id, stage_id, purpose="write"):
        body = StageRequest(
            candidate_id=subject,
            purpose=purpose,
            session_id=session_id,
            stage_id=stage_id,
            nonce=uuid4(),
            requester=self.settings.service_name,
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self.send_stage(
                canonical(body), sign(self.signatures, STAGE_REQUEST_CONTEXT, body)
            )
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized response")
            status = StageStatus.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, STAGE_RESPONSE_CONTEXT, status)
            if (
                raw != canonical(status)
                or not fresh(status.issued_at)
                or any(
                    getattr(status, key) != getattr(body, key)
                    for key in (
                        "candidate_id",
                        "session_id",
                        "stage_id",
                        "nonce",
                        "requester",
                        "purpose",
                    )
                )
                or status.allowed != (status.format is not None)
            ):
                raise ValueError("Invalid stage binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not status.allowed:
            raise HTTPException(409)
        return status.format
