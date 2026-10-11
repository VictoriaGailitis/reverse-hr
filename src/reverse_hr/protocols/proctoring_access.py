"""Fresh signed integrity summaries for Evaluation; never part of a competence score."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request

from reverse_hr.protocols.processing_access import ProcessingAccess, ProcessingRequest
from reverse_hr.services.proctoring.domain.proctoring import IntegritySummary
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.signing import canonical, fresh, sign, verify

REQUEST = b"reverse-hr.integrity-request.v1\0"
RESPONSE = b"reverse-hr.integrity-response.v1\0"
MAX_BYTES = 524288


class IntegrityRequest(ProcessingRequest):
    requester: Literal["evaluation"]
    session_id: UUID
    stage_id: UUID


class IntegrityReceipt(IntegrityRequest):
    summary: IntegritySummary


class IntegrityAccess(ProcessingAccess):
    def fetch(self, candidate_id, session_id, stage_id):
        body = IntegrityRequest(
            candidate_id=candidate_id,
            session_id=session_id,
            stage_id=stage_id,
            requester="evaluation",
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self._send(
                "integrity-summary",
                canonical(body),
                sign(self.signatures, REQUEST, body),
                origin=self.settings.proctoring_api_url,
                max_bytes=MAX_BYTES,
            )
            result = IntegrityReceipt.model_validate_json(raw)
            verify(self.signatures, "proctoring", signature, RESPONSE, result)
            if (
                len(raw) > MAX_BYTES
                or raw != canonical(result)
                or not fresh(result.issued_at)
                or any(
                    getattr(result, key) != getattr(body, key)
                    for key in type(body).model_fields
                    if key != "issued_at"
                )
                or any(
                    getattr(result.summary, key) != getattr(body, key)
                    for key in ("candidate_id", "session_id", "stage_id")
                )
            ):
                raise ValueError("Invalid integrity binding")
        except Exception as exc:
            raise HTTPException(503) from exc
        return result.summary


router = APIRouter(prefix="/v1/evaluations", tags=["integrity"])


@router.get("/{stage_id}/integrity", response_model=IntegritySummary)
def evaluation_integrity(request: Request, actor: Actor, stage_id: UUID):
    from sqlalchemy.orm import Session

    from reverse_hr.services.evaluation.domain.evaluation import EvaluationIntake, subject_lock

    actor.require("assessment_reviewer", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        row = session.get(EvaluationIntake, str(stage_id))
        if row is None:
            raise HTTPException(404)
        if row.candidate_id == str(actor.subject):
            raise HTTPException(403)
        for subject in sorted({str(actor.subject), row.candidate_id}):
            subject_lock(session, UUID(subject))
        request.app.state.processing_access.check(UUID(row.candidate_id))
        result = request.app.state.integrity_access.fetch(
            UUID(row.candidate_id), UUID(row.session_id), stage_id
        )
        request.app.state.processing_access.check(UUID(row.candidate_id))
        return result
