"""Immutable signed demo-suite verdicts, no candidate score or grade promotion."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import JSON, DateTime, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.suite_validation import (
    CaseCapture,
    ValidationPlan,
    compare_bound_captures,
)
from reverse_hr.contracts.suite_verdict import VERDICT_CONTEXT as VERDICT_CONTEXT
from reverse_hr.contracts.suite_verdict import CaptureMatrix as CaptureMatrix
from reverse_hr.contracts.suite_verdict import SuiteVerdict as SuiteVerdict
from reverse_hr.contracts.test_suites import digest
from reverse_hr.services.code_runner.domain.code_runner import RunnerBase, subject_lock
from reverse_hr.services.code_runner.runner_readiness import fingerprint, require_execution_ready
from reverse_hr.services.code_runner.sandbox import SandboxUnavailable
from reverse_hr.services.code_runner.validation_lifecycle import (
    ValidationAttempt,
    ValidationBatch,
    ValidationCapture,
    completed_prefix,
)
from reverse_hr.shared.db import enqueue
from reverse_hr.shared.signing import sign, verify


class VerdictRecord(RunnerBase):
    __tablename__ = "validation_verdicts"
    validation_id: Mapped[str] = mapped_column(
        ForeignKey("validation_batches.validation_id"), primary_key=True
    )
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    proof: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String(128))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def snapshot(session, owner, validation_id, executor):
    row = session.get(ValidationBatch, str(validation_id), populate_existing=True)
    if row is None or row.owner_id != str(owner):
        raise HTTPException(404)
    if row.status not in {"captures_ready", "accepted", "rejected"} or row.plan is None:
        raise HTTPException(409)
    try:
        plan = ValidationPlan.model_validate(row.plan)
        if str(plan.validation_id) != row.validation_id or completed_prefix(
            session, row, plan
        ) != len(plan.inputs):
            raise ValueError("Incomplete matrix")
        attempts = session.scalars(
            select(ValidationAttempt)
            .where(ValidationAttempt.validation_id == row.validation_id)
            .order_by(ValidationAttempt.ordinal)
        ).all()
        scope = executor.cleanup_scope()
        if any(
            item.node_id != str(executor.settings.runner_node_id) or item.scope_id != scope
            for item in attempts
        ):
            raise ValueError("Foreign execution environment")
        captures = [
            CaseCapture.model_validate(session.get(ValidationCapture, item.attempt_id).capture)
            for item in attempts
        ]
        return plan, CaptureMatrix(captures=captures)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(409) from exc


def finalize(engine, owner_id, validation_id, access, material_access, executor, signatures):
    """Fresh trusted material and readiness on every replay; never infer from stdout claims."""
    owner, validation_id = UUID(str(owner_id)), UUID(str(validation_id))
    require_execution_ready(executor)
    with Session(engine) as session, session.begin():
        subject_lock(session, owner)
        access.check(owner)
        plan, matrix = snapshot(session, owner, validation_id, executor)
    if fingerprint(executor) != plan.pin.runtime_fingerprint:
        raise SandboxUnavailable()
    definition = material_access.fetch(owner, plan)
    verdict = compare_bound_captures(definition, plan, matrix.captures)
    if verdict == "inconclusive":
        raise HTTPException(409)
    require_execution_ready(executor)
    if fingerprint(executor) != plan.pin.runtime_fingerprint:
        raise SandboxUnavailable()
    with Session(engine) as session, session.begin():
        subject_lock(session, owner)
        access.check(owner)
        current_plan, current_matrix = snapshot(session, owner, validation_id, executor)
        if current_plan != plan or current_matrix != matrix:
            raise HTTPException(409)
        row = session.get(VerdictRecord, str(validation_id))
        if row is not None:
            try:
                proof = SuiteVerdict.model_validate(row.proof)
                verify(signatures, "code-runner", row.signature, VERDICT_CONTEXT, proof)
            except Exception as exc:
                raise HTTPException(409) from exc
            if (
                row.owner_id != str(owner)
                or session.get(ValidationBatch, str(validation_id)).status != verdict
                or proof.owner_id != owner
                or proof.validation_id != validation_id
                or proof.pin != plan.pin
                or proof.plan_digest != digest(plan)
                or proof.captures_digest != digest(matrix)
                or proof.captures_count != len(matrix.captures)
                or proof.verdict != verdict
            ):
                raise HTTPException(409)
            return proof, row.signature
        if session.get(ValidationBatch, str(validation_id)).status != "captures_ready":
            raise HTTPException(409)
        proof = SuiteVerdict(
            validation_id=validation_id,
            owner_id=owner,
            pin=plan.pin,
            plan_digest=digest(plan),
            captures_digest=digest(matrix),
            captures_count=len(matrix.captures),
            verdict=verdict,
            completed_at=datetime.now(UTC),
        )
        try:
            signed = sign(signatures, VERDICT_CONTEXT, proof)
            verify(signatures, "code-runner", signed, VERDICT_CONTEXT, proof)
        except Exception as exc:
            raise HTTPException(503) from exc
        session.add(
            VerdictRecord(
                validation_id=str(validation_id),
                owner_id=str(owner),
                proof=proof.model_dump(mode="json"),
                signature=signed,
                completed_at=proof.completed_at,
            )
        )
        session.get(ValidationBatch, str(validation_id)).status = verdict
        enqueue(
            session,
            EventEnvelope(
                event_type="code-runner.validation_verdict_recorded.v1",
                producer="code-runner",
                aggregate_id=validation_id,
                aggregate_version=2,
                correlation_id=validation_id,
                payload={"candidate_id": owner, "validation_id": validation_id},
            ),
        )
    return proof, signed
