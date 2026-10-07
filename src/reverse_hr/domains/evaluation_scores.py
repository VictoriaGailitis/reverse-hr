"""Export reviewed stage evidence for the separate session grade decision."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reverse_hr.domains.evaluation import EvaluationIntake, subject_lock
from reverse_hr.domains.evaluation_review import (
    ReviewCommand,
    ReviewRecord,
    review_view,
    validate_decisions,
)
from reverse_hr.domains.evaluation_tests import ResultNonce, test_points
from reverse_hr.evaluation_access import PinnedMaterial
from reverse_hr.event_transport import Signatures
from reverse_hr.grade_access import (
    REQUEST,
    RESPONSE,
    CriterionScore,
    ScoreReceipt,
    ScoreRequest,
    StageScore,
)
from reverse_hr.processing_access import canonical, fresh, sign, verify
from reverse_hr.test_suites import digest

router = APIRouter(prefix="/internal/v1", tags=["internal-session-scores"])


@router.post("/stage-score", response_model=ScoreReceipt)
def stage_score(
    request: Request,
    body: ScoreRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "evaluation_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, body.requester, signature, REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    refs = {
        k: getattr(body, k)
        for k in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
    }
    current = request.app.state.material_access.fetch(**refs)
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(ResultNonce).where(ResultNonce.expires_at < now))
            session.add(ResultNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            subject = subject_lock(session, body.candidate_id, allow_blocked=True)
            row = session.get(EvaluationIntake, str(body.stage_id))
            allowed = bool(
                not subject.blocked
                and row
                and all(getattr(row, k) == str(v) for k, v in refs.items())
                and row.material
                and row.material == current.model_dump(mode="json")
            )
            stage = None
            if allowed:
                request.app.state.processing_access.check_assessment(
                    body.candidate_id, current.consent_id
                )
                material = PinnedMaterial.model_validate(row.material)
                review = (
                    session.query(ReviewRecord)
                    .filter_by(stage_id=row.stage_id, number=row.review_number)
                    .one_or_none()
                    if row.review_number
                    else None
                )
                decisions = {d["criterion_key"]: d for d in review.decisions} if review else {}
                model_attempt = None
                if review and review.model_attempt_id:
                    from reverse_hr.evaluation_llm import ModelAttempt, ModelInput

                    model_attempt = session.get(ModelAttempt, review.model_attempt_id)
                    if (
                        model_attempt is None
                        or model_attempt.status != "ready"
                        or model_attempt.stage_id != row.stage_id
                        or model_attempt.candidate_id != row.candidate_id
                        or model_attempt.input_digest
                        != digest(ModelInput(material=row.material, source=row.source))
                    ):
                        raise HTTPException(409)
                if review:
                    from reverse_hr.domains.coding_workspace import FilesCommand

                    if digest(FilesCommand.model_validate(row.source)) != material.snapshot_digest:
                        raise HTTPException(409)
                    test_scores, proof_digest = test_points(session, row, signatures)
                    command = ReviewCommand(
                        decisions=review.decisions,
                        reason=review.reason,
                        model_attempt_id=review.model_attempt_id,
                    )
                    if validate_decisions(row, command, test_scores, proof_digest) != review.score:
                        raise HTTPException(409)
                if review and review.score != row.score:
                    raise HTTPException(409)
                stage = StageScore(
                    model_attempt_id=model_attempt.attempt_id if model_attempt else None,
                    llm_model=model_attempt.model if model_attempt else None,
                    llm_prompt_digest=model_attempt.prompt_digest if model_attempt else None,
                    snapshot_version=material.snapshot_version,
                    snapshot_digest=material.snapshot_digest,
                    revision_id=material.revision_id,
                    content_digest=material.content_digest,
                    task_key=material.task.key,
                    review_id=review.review_id if review else None,
                    reviewer_id=review.reviewer_id if review else None,
                    criteria=[
                        CriterionScore(
                            criterion_key=c.key,
                            competency=c.competency,
                            max_points=c.points,
                            points=decisions[c.key]["points"] if review else None,
                            evidence_type=c.evidence,
                        )
                        for c in material.task.rubric
                    ],
                    score=row.score if review else None,
                    evidence_digest=digest(review_view(review)) if review else digest(material),
                )
            receipt = ScoreReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=allowed,
                stage=stage,
            )
            raw, signed = canonical(receipt), sign(signatures, RESPONSE, receipt)
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
