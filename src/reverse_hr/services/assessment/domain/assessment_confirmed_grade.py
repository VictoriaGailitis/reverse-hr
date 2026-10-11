"""Signed reviewed decisions and bounded competency evidence; no raw submissions."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.qualification_contracts import QualificationEvidence
from reverse_hr.contracts.test_suites import digest
from reverse_hr.protocols.confirmed_grade_access import (
    REQUEST,
    RESPONSE,
    DecisionReceipt,
    DecisionRequest,
    DecisionSummary,
)
from reverse_hr.services.assessment.domain.assessment_appeals import AppealDecision
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_grades import (
    GradeDecision,
    GradePolicy,
    Rules,
    policy_owners,
    utc,
)
from reverse_hr.services.assessment.domain.assessment_sessions import PracticalSession, subject_lock
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, fresh, sign, verify


class DecisionEvidence(Contract):
    data: dict


router = APIRouter(prefix="/internal/v1", tags=["internal-confirmed-grade"])


@router.post("/confirmed-grade", response_model=DecisionReceipt)
def confirmed_grade(
    request: Request,
    body: DecisionRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "assessment_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, "candidate", signature, REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(MaterialNonce).where(MaterialNonce.expires_at < now))
            session.add(
                MaterialNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60))
            )
            session.flush()
            row = session.get(PracticalSession, str(body.session_id))
            decision = session.get(GradeDecision, str(body.decision_id))
            corrected = session.get(AppealDecision, str(body.decision_id))
            if corrected:
                decision = corrected
            correction = session.scalar(
                select(AppealDecision).where(AppealDecision.session_id == str(body.session_id))
            )
            expected_version = (
                corrected.session_version
                if corrected
                else correction.previous_session_version
                if correction
                else row.version
                if row
                else 0
            )
            result = None
            if (
                row
                and decision
                and row.status == "completed"
                and expected_version == body.session_version
                and row.candidate_id == str(body.candidate_id)
                and decision.session_id == row.session_id
                and decision.candidate_id == row.candidate_id
                and decision.reviewer_id == str(body.reviewer_id)
            ):
                try:
                    from reverse_hr.contracts.automation import human_owners

                    owners = human_owners(
                        policy_owners(request, session, row) | {decision.reviewer_id}
                    )
                    for owner in sorted(owners):
                        subject_lock(session, owner)
                        request.app.state.processing_access.check(UUID(owner))
                    request.app.state.processing_access.check_assessment(
                        body.candidate_id, UUID(row.consent_id)
                    )
                    qualification = None
                    policy = session.get(GradePolicy, decision.evidence.get("policy_id"))
                    if policy and decision.score is not None and decision.competency_scores:
                        rules = Rules.model_validate(policy.rules)
                        qualification = QualificationEvidence(
                            origin=getattr(decision, "origin", "human"),
                            policy_id=policy.policy_id,
                            evidence_digest=digest(DecisionEvidence(data=decision.evidence)),
                            assessed_at=utc(decision.created_at),
                            score=decision.score,
                            competency_scores=decision.competency_scores,
                            competency_minimums=rules.minimums,
                            next_attempt_at=utc(decision.next_attempt_at),
                            grade_change_available_at=utc(decision.created_at)
                            + timedelta(seconds=rules.grade_change_seconds),
                        )
                    result = DecisionSummary(
                        qualification=qualification,
                        origin=getattr(decision, "origin", "human"),
                        specialization=decision.specialization,
                        target_grade=decision.target_grade,
                        status=decision.status,
                        decided_at=utc(decision.created_at),
                        decision_revision=2 if corrected else 1,
                        supersedes_decision_id=corrected.original_decision_id
                        if corrected
                        else None,
                    )
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
            receipt = DecisionReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=result is not None,
                decision=result,
            )
            raw, signed = canonical(receipt), sign(signatures, RESPONSE, receipt)
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
