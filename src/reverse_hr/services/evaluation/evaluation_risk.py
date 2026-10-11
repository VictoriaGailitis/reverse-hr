"""Persistent risk signals and independent, evidence-bound verification."""

from datetime import UTC, datetime
from typing import Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.practical_evidence import source_model
from reverse_hr.contracts.test_suites import digest
from reverse_hr.protocols.evaluation_access import PinnedMaterial
from reverse_hr.services.evaluation.domain.evaluation import (
    EvaluationBase,
    EvaluationIntake,
    subject_lock,
)
from reverse_hr.services.evaluation.domain.evaluation_review import (
    ReviewRecord,
    independent_company_reviewer,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import enqueue
from reverse_hr.shared.prompt_injection import RULE_VERSION, scan_source


class EvaluationRisk(EvaluationBase):
    __tablename__ = "evaluation_risks"
    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    source_digest: Mapped[str] = mapped_column(String(64))
    codes: Mapped[list] = mapped_column(JSON)
    rule_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(32))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    reviewer_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(String(2000))
    verification_stage_id: Mapped[str | None] = mapped_column(String(36))


def register(session, intake, extra_codes=()):
    codes = sorted(set(scan_source(intake.source)) | set(extra_codes))
    if not codes or session.get(EvaluationRisk, intake.stage_id):
        return
    row = EvaluationRisk(
        stage_id=intake.stage_id,
        candidate_id=intake.candidate_id,
        source_digest=digest(source_model(intake.source)),
        codes=codes,
        rule_version=RULE_VERSION,
        status="review_pending",
        version=1,
        created_at=datetime.now(UTC),
    )
    session.add(row)
    enqueue(
        session,
        EventEnvelope(
            event_type="evaluation.risk_detected.v1",
            producer="evaluation",
            correlation_id=uuid4(),
            aggregate_id=uuid5(NAMESPACE_URL, "evaluation-risk:" + intake.stage_id),
            aggregate_version=1,
            payload={
                "candidate_id": UUID(intake.candidate_id),
                "stage_id": UUID(intake.stage_id),
            },
        ),
    )
    session.flush()


def requires_verification(session, candidate_id):
    return (
        session.scalar(
            select(EvaluationRisk.stage_id)
            .where(
                EvaluationRisk.candidate_id == str(candidate_id),
                EvaluationRisk.status.in_(["review_pending", "verification_required"]),
            )
            .limit(1)
        )
        is not None
    )


router = APIRouter(prefix="/v1/evaluation-risks", tags=["evaluation-risks"])


def permitted(request, actor, session, row):
    subject_lock(session, UUID(row.candidate_id))
    intake = session.get(EvaluationIntake, row.stage_id)
    if intake is None or not intake.material:
        raise HTTPException(404)
    material = PinnedMaterial.model_validate(intake.material)
    request.app.state.processing_access.check_assessment(
        UUID(row.candidate_id), material.consent_id
    )
    if actor.subject != UUID(row.candidate_id):
        independent_company_reviewer(request, actor, material)
    return intake


def view(row):
    return dict(
        stage_id=row.stage_id,
        candidate_id=row.candidate_id,
        codes=row.codes,
        rule_version=row.rule_version,
        status=row.status,
        version=row.version,
        created_at=row.created_at.isoformat(),
        reason=row.reason,
        verification_stage_id=row.verification_stage_id,
    )


@router.get("/me")
def mine(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        rows = list(
            session.scalars(
                select(EvaluationRisk).where(EvaluationRisk.candidate_id == str(actor.subject))
            )
        )
        for row in rows:
            permitted(request, actor, session, row)
        return {
            "additional_verification_required": requires_verification(session, actor.subject),
            "signal_count": sum(len(row.codes) for row in rows),
            "items": [view(row) for row in rows],
        }


@router.get("/queue")
def queue(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("assessment_reviewer", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        query = select(EvaluationRisk).where(
            EvaluationRisk.status.in_(["review_pending", "verification_required"]),
            EvaluationRisk.candidate_id != str(actor.subject),
        )
        if after:
            query = query.where(EvaluationRisk.stage_id > str(after))
        rows = list(session.scalars(query.order_by(EvaluationRisk.stage_id).limit(101)))
        result = []
        for row in rows[:100]:
            try:
                permitted(request, actor, session, row)
            except HTTPException as exc:
                if exc.status_code in {403, 404, 409}:
                    continue
                raise
            result.append(view(row))
        return {"items": result, "next_cursor": rows[99].stage_id if len(rows) > 100 else None}


class RiskDecision(Contract):
    action: Literal["dismiss", "require_verification", "complete_verification"]
    reason: str = Field(min_length=10, max_length=2000, pattern=r"\S")
    verification_stage_id: UUID | None = None


@router.post("/{stage_id}/decision")
def decide(
    stage_id: UUID,
    request: Request,
    actor: Actor,
    body: RiskDecision,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("assessment_reviewer", mfa=True)

    def guard(session):
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)

    def change(session):
        row = session.get(EvaluationRisk, str(stage_id))
        if row is None:
            raise HTTPException(404)
        if row.candidate_id == str(actor.subject):
            raise HTTPException(403)
        permitted(request, actor, session, row)
        session.refresh(row, with_for_update=True)
        if row.version != int(if_match.strip('"')) or row.status not in {
            "review_pending",
            "verification_required",
        }:
            raise HTTPException(409)
        if body.action == "complete_verification":
            if body.verification_stage_id is None or body.verification_stage_id == stage_id:
                raise HTTPException(422, "A separate reviewed task is required")
            other = session.get(EvaluationIntake, str(body.verification_stage_id))
            review = session.scalar(
                select(ReviewRecord).where(
                    ReviewRecord.stage_id == str(body.verification_stage_id),
                    ReviewRecord.number == (other.review_number if other else -1),
                )
            )
            created = (
                row.created_at.replace(tzinfo=UTC)
                if row.created_at.tzinfo is None
                else row.created_at
            )
            if (
                other is None
                or other.candidate_id != row.candidate_id
                or review is None
                or other.received_at is None
                or (
                    other.received_at.replace(tzinfo=UTC)
                    if other.received_at.tzinfo is None
                    else other.received_at
                )
                < created
                or review.origin != "human"
                or review.score is None
                or review.reviewer_id == row.candidate_id
                or (
                    review.created_at.replace(tzinfo=UTC)
                    if review.created_at.tzinfo is None
                    else review.created_at
                )
                < created
            ):
                raise HTTPException(409, "Fresh independent human-reviewed evidence is required")
            material = PinnedMaterial.model_validate(other.material)
            request.app.state.processing_access.check_assessment(
                UUID(row.candidate_id), material.consent_id
            )
            request.app.state.processing_access.check(UUID(review.reviewer_id))
            independent_company_reviewer(request, actor, material)
            row.verification_stage_id = str(body.verification_stage_id)
            row.status = "verified"
        else:
            if body.verification_stage_id is not None:
                raise HTTPException(422)
            row.status = "dismissed" if body.action == "dismiss" else "verification_required"
        row.reviewer_id, row.reason = str(actor.subject), body.reason
        row.version += 1
        enqueue(
            session,
            EventEnvelope(
                event_type="evaluation.risk_decision_recorded.v1",
                producer="evaluation",
                correlation_id=request.state.trace_id,
                aggregate_id=uuid5(NAMESPACE_URL, "evaluation-risk:" + str(stage_id)),
                aggregate_version=row.version,
                payload={
                    "candidate_id": UUID(row.candidate_id),
                    "stage_id": stage_id,
                },
            ),
        )
        return view(row)

    def present(session, _):
        row = session.get(EvaluationRisk, str(stage_id))
        if row is None or row.candidate_id == str(actor.subject):
            raise HTTPException(404)
        permitted(request, actor, session, row)
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"risk_decision:{stage_id}",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
        change,
        guard=guard,
        present=present,
    )
