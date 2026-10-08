"""Signed, fresh service requests for Privacy's current processing restriction."""

import base64
import json
from datetime import UTC, datetime
from typing import Literal
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import Field

from reverse_hr.contracts import Contract

REQUEST_CONTEXT = b"reverse-hr.processing-request.v1\0"
RESPONSE_CONTEXT = b"reverse-hr.processing-response.v1\0"
ASSESSMENT_REQUEST_CONTEXT = b"reverse-hr.assessment-permission-request.v1\0"
ASSESSMENT_RESPONSE_CONTEXT = b"reverse-hr.assessment-permission-response.v1\0"
MAX_BYTES = 4096


class ProcessingRequest(Contract):
    candidate_id: UUID
    nonce: UUID
    requester: Literal[
        "candidate",
        "employer",
        "assessment",
        "coding-workspace",
        "code-runner",
        "evaluation",
        "matching",
        "hiring",
        "notification",
        "media",
        "whiteboard",
        "proctoring",
    ]
    issued_at: datetime


class ProcessingStatus(ProcessingRequest):
    allowed: bool = Field(strict=True)


class AssessmentPermissionRequest(ProcessingRequest):
    requester: Literal["assessment", "evaluation"]
    consent_id: UUID


class AssessmentPermissionStatus(AssessmentPermissionRequest):
    allowed: bool = Field(strict=True)


def canonical(model):
    return json.dumps(model.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


def fresh(value, *, now=None):
    now = now or datetime.now(UTC)
    return value.tzinfo is not None and abs((now - value).total_seconds()) <= 30


def sign(signatures, context, model):
    return base64.b64encode(signatures.private.sign(context + canonical(model))).decode()


def verify(signatures, producer, signature, context, model):
    signatures.public[producer].verify(
        base64.b64decode(signature, validate=True), context + canonical(model)
    )


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class ProcessingAccess:
    def __init__(self, settings):
        self.settings = settings
        self._signatures = None
        # Ignore ambient proxy configuration; do not redirect signed requests elsewhere.
        self.opener = build_opener(ProxyHandler({}), NoRedirect())

    @property
    def signatures(self):
        if self._signatures is None:
            from reverse_hr.event_transport import Signatures

            self._signatures = Signatures.from_settings(self.settings)
        return self._signatures

    def send(self, body, signature):
        return self._send("processing-status", body, signature)

    def send_assessment(self, body, signature):
        return self._send("assessment-permission", body, signature)

    def _send(self, endpoint, body, signature, *, origin=None, max_bytes=MAX_BYTES):
        request = Request(
            (origin or self.settings.privacy_api_url).rstrip("/") + "/internal/v1/" + endpoint,
            data=body,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
            method="POST",
        )
        with self.opener.open(request, timeout=3) as response:
            if response.status != 200:
                raise ValueError("Unavailable")
            return response.read(max_bytes + 1), response.headers.get("X-HR-Signature", "")

    def check(self, subject):
        request = ProcessingRequest(
            candidate_id=subject,
            nonce=uuid4(),
            requester=self.settings.service_name,
            issued_at=datetime.now(UTC),
        )
        try:
            signature = sign(self.signatures, REQUEST_CONTEXT, request)
            raw, response_signature = self.send(canonical(request), signature)
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized response")
            status = ProcessingStatus.model_validate_json(raw)
            verify(self.signatures, "privacy", response_signature, RESPONSE_CONTEXT, status)
            if (
                raw != canonical(status)
                or status.nonce != request.nonce
                or status.candidate_id != request.candidate_id
                or status.requester != request.requester
                or not fresh(status.issued_at)
            ):
                raise ValueError("Invalid response binding")
        except Exception as exc:
            # Never surface credentials, request UUIDs, network details or exception text.
            raise HTTPException(503) from exc
        if not status.allowed:
            raise HTTPException(409)

    def check_assessment(self, subject, consent_id):
        request = AssessmentPermissionRequest(
            candidate_id=subject,
            consent_id=consent_id,
            nonce=uuid4(),
            requester=self.settings.service_name,
            issued_at=datetime.now(UTC),
        )
        try:
            signature = sign(self.signatures, ASSESSMENT_REQUEST_CONTEXT, request)
            raw, response_signature = self.send_assessment(canonical(request), signature)
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized response")
            status = AssessmentPermissionStatus.model_validate_json(raw)
            verify(
                self.signatures, "privacy", response_signature, ASSESSMENT_RESPONSE_CONTEXT, status
            )
            if (
                raw != canonical(status)
                or status.nonce != request.nonce
                or status.candidate_id != request.candidate_id
                or status.consent_id != request.consent_id
                or status.requester != request.requester
                or not fresh(status.issued_at)
            ):
                raise ValueError("Invalid permission binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not status.allowed:
            raise HTTPException(409)
