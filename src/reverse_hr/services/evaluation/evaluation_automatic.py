"""Evidence-checked machine stage reviews; uncertainty routes to a human queue."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, Request
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.automation import AUTOMATIC_REVIEWER
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.test_suites import digest
from reverse_hr.services.evaluation.domain.evaluation import (
    EvaluationBase,
    EvaluationIntake,
    subject_lock,
)
from reverse_hr.services.evaluation.domain.evaluation_review import (
    CriterionDecision,
    ReviewCommand,
    ReviewRecord,
    validate_decisions,
)
from reverse_hr.services.evaluation.domain.evaluation_tests import test_points
from reverse_hr.services.evaluation.evaluation_llm import (
    PROMPT,
    PROMPT_VERSION,
    ModelAttempt,
    ModelInput,
    attempt_input_digest,
    emit_attempt,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.db import enqueue


class AutomaticStageReview(EvaluationBase):
    __tablename__ = "evaluation_automatic_reviews"
    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(100))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


router = APIRouter(prefix="/v1/evaluation-automatic", tags=["automatic-evaluation"])


@router.get("/configuration")
def configuration(request: Request, actor: Actor):
    actor.require("content_admin", mfa=True)
    request.app.state.processing_access.check(actor.subject)
    settings = request.app.state.settings
    return dict(
        enabled=bool(
            settings.evaluation_llm_enabled
            and settings.evaluation_llm_model
            and settings.evaluation_llm_config
        ),
        model=settings.evaluation_llm_model or None,
        prompt_digest=hashlib.sha256(PROMPT.encode()).hexdigest(),
        proposals=settings.evaluation_automatic_proposals,
        disagreement=settings.evaluation_automatic_disagreement,
    )


@router.get("/queue")
def queue(request: Request, actor: Actor, limit: int = 50):
    actor.require("assessment_reviewer", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        rows = session.scalars(
            select(AutomaticStageReview)
            .where(AutomaticStageReview.status == "review_pending")
            .order_by(AutomaticStageReview.updated_at)
            .limit(max(1, min(limit, 100)))
        )
        result = []
        for row in rows:
            if row.candidate_id == str(actor.subject):
                continue
            intake = session.get(EvaluationIntake, row.stage_id)
            if intake is None or intake.review_number or not intake.material:
                continue
            from reverse_hr.protocols.evaluation_access import PinnedMaterial
            from reverse_hr.services.evaluation.domain.evaluation_review import (
                independent_company_reviewer,
            )

            material = PinnedMaterial.model_validate(intake.material)
            request.app.state.processing_access.check_assessment(
                UUID(row.candidate_id), material.consent_id
            )
            independent_company_reviewer(request, actor, material)
            result.append(dict(stage_id=row.stage_id, reason=row.reason, updated_at=row.updated_at))
        return result


def run_one(
    engine,
    settings,
    material_access,
    artifact_access,
    processing,
    signatures,
    integrity_access=None,
):
    if not settings.evaluation_automatic_enabled:
        return False
    with Session(engine) as session:
        ids = list(
            session.scalars(
                select(EvaluationIntake.stage_id)
                .where(
                    EvaluationIntake.status.in_(["artifact_ready", "needs_evidence"]),
                    EvaluationIntake.source.is_not(None),
                    EvaluationIntake.material.is_not(None),
                )
                .order_by(EvaluationIntake.stage_id)
            )
        )
        # Rotate waiting items so one missing provider/result does not starve others.
        times = {
            r.stage_id: (
                r.updated_at.replace(tzinfo=UTC) if r.updated_at.tzinfo is None else r.updated_at
            ).timestamp()
            for r in session.scalars(select(AutomaticStageReview))
        }
        ids.sort(key=lambda key: times.get(key, 0))
    for stage_id in ids:
        with Session(engine) as session:
            row = session.get(EvaluationIntake, stage_id)
            if row is None or row.review_number:
                continue
            refs = {
                key: UUID(getattr(row, key))
                for key in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
            }
            original_material, original_source = row.material, row.source
        material = material_access.fetch(**refs)
        source = artifact_access.fetch(
            **refs,
            format=material.task.format,
            snapshot_version=material.snapshot_version,
            digest=material.snapshot_digest,
        )
        if (
            material.model_dump(mode="json") != original_material
            or source.model_dump(mode="json") != original_source
        ):
            continue
        integrity_reason = None
        if integrity_access is not None:
            integrity = integrity_access.fetch(
                refs["candidate_id"], refs["session_id"], refs["stage_id"]
            )
            if integrity.status in {"concern", "inconclusive"} or (
                integrity.flags and integrity.status != "clear"
            ):
                integrity_reason = "integrity_review"
        with Session(engine) as session, session.begin():
            subject_lock(session, refs["candidate_id"])
            processing.check_assessment(refs["candidate_id"], material.consent_id)
            row = session.scalar(
                select(EvaluationIntake)
                .where(EvaluationIntake.stage_id == stage_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if (
                row is None
                or row.review_number
                or row.material != original_material
                or row.source != original_source
            ):
                continue
            state = session.get(AutomaticStageReview, stage_id)
            if state is None:
                state = AutomaticStageReview(
                    stage_id=stage_id,
                    candidate_id=row.candidate_id,
                    status="waiting",
                    updated_at=datetime.now(UTC),
                )
                session.add(state)
            state.updated_at = datetime.now(UTC)

            def pending(reason, state=state):
                state.status, state.reason = "review_pending", reason

            from reverse_hr.services.evaluation.evaluation_risk import (
                register,
                requires_verification,
            )

            register(
                session,
                row,
                ["proctoring_concern"]
                if integrity_reason and integrity.status == "concern"
                else [],
            )
            if requires_verification(session, row.candidate_id):
                pending("additional_verification_required")
                return True
            if integrity_reason:
                pending(integrity_reason)
                return True
            tests, proof = test_points(session, row, signatures)
            rubric = material.task.rubric
            if any(c.evidence == "test_result" and tests.get(c.key) is None for c in rubric):
                state.status, state.reason = "waiting", "test_evidence_pending"
                return True
            proposals = []
            non_test = [c for c in rubric if c.evidence != "test_result"]
            attempts = list(
                session.scalars(
                    select(ModelAttempt)
                    .where(ModelAttempt.stage_id == stage_id)
                    .order_by(ModelAttempt.number)
                )
            )
            model_attempt = None
            if non_test:
                if (
                    not settings.evaluation_llm_enabled
                    or not settings.evaluation_llm_model
                    or settings.evaluation_llm_config is None
                ):
                    pending("model_unavailable")
                    return True
                config = settings.evaluation_llm_config.model_dump(mode="json")
                if any(
                    a.model != settings.evaluation_llm_model or a.gateway_configuration != config
                    for a in attempts
                ):
                    pending("model_configuration_changed")
                    return True
                ready = [
                    a
                    for a in attempts
                    if a.status == "ready"
                    and a.input_digest == attempt_input_digest(a, row.material, row.source)
                ]
                if len(ready) < settings.evaluation_automatic_proposals:
                    if any(a.status in {"pending", "running"} for a in attempts):
                        state.status, state.reason = "waiting", "model_pending"
                        return True
                    if len(attempts) >= 3:
                        pending("model_technical_failure")
                        return True
                    attempt = ModelAttempt(
                        attempt_id=str(uuid4()),
                        stage_id=stage_id,
                        candidate_id=row.candidate_id,
                        requested_by=str(AUTOMATIC_REVIEWER),
                        number=len(attempts) + 1,
                        model=settings.evaluation_llm_model,
                        prompt_version=PROMPT_VERSION,
                        prompt_digest=hashlib.sha256(PROMPT.encode()).hexdigest(),
                        gateway_configuration=config,
                        input_digest=digest(ModelInput(material=material, source=source)),
                        status="pending",
                        created_at=datetime.now(UTC),
                    )
                    session.add(attempt)
                    emit_attempt(session, attempt, "requested", 1)
                    state.status, state.reason = "waiting", "model_pending"
                    return True
                proposals = [
                    ReviewCommand.model_validate(a.output)
                    for a in ready[: settings.evaluation_automatic_proposals]
                ]
                model_attempt = ready[0]
                for proposal in proposals:
                    validate_decisions(row, proposal)
                for criterion in non_test:
                    points = [
                        next(d for d in p.decisions if d.criterion_key == criterion.key).points
                        for p in proposals
                    ]
                    if any(point is None for point in points):
                        pending("incomplete_model_evidence")
                        return True
                    if (
                        max(points) - min(points)
                    ) * 100 > settings.evaluation_automatic_disagreement * criterion.points:
                        pending("model_disagreement")
                        return True
            decisions = []
            for criterion in rubric:
                if criterion.evidence == "test_result":
                    decisions.append(
                        CriterionDecision(
                            criterion_key=criterion.key,
                            points=tests[criterion.key],
                            reason="Verified pinned Runner evidence",
                            test_proof_digest=proof,
                        )
                    )
                else:
                    decisions.append(
                        min(
                            (
                                next(d for d in p.decisions if d.criterion_key == criterion.key)
                                for p in proposals
                            ),
                            key=lambda d: d.points,
                        )
                    )
            body = ReviewCommand(
                decisions=decisions,
                reason="Automatic evidence-checked rubric evaluation",
                model_attempt_id=UUID(model_attempt.attempt_id) if model_attempt else None,
            )
            score = validate_decisions(row, body, tests, proof)
            if score is None:
                pending("incomplete_evidence")
                return True
            row.version += 1
            row.review_number += 1
            row.status, row.score = "reviewed", score
            review = ReviewRecord(
                origin="automatic",
                review_id=str(uuid4()),
                stage_id=stage_id,
                candidate_id=row.candidate_id,
                reviewer_id=str(AUTOMATIC_REVIEWER),
                number=row.review_number,
                intake_version=row.version,
                model_attempt_id=model_attempt.attempt_id if model_attempt else None,
                decisions=body.model_dump(mode="json")["decisions"],
                score=score,
                reason=body.reason,
                created_at=datetime.now(UTC),
            )
            session.add(review)
            state.status, state.reason = "scored", None
            enqueue(
                session,
                EventEnvelope(
                    event_type="evaluation.review_recorded.v1",
                    producer="evaluation",
                    aggregate_id=refs["stage_id"],
                    aggregate_version=row.version,
                    correlation_id=refs["session_id"],
                    payload={
                        "candidate_id": refs["candidate_id"],
                        "stage_id": refs["stage_id"],
                        "review_id": UUID(review.review_id),
                        "reviewer_id": AUTOMATIC_REVIEWER,
                    },
                ),
            )
            return True
    return False
