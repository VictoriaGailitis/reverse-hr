"""Suite-validation execution and durable physical cleanup obligations."""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.runner import Output
from reverse_hr.contracts.suite_validation import CaseCapture, ValidationPlan, build_plan
from reverse_hr.contracts.test_suites import SuiteDefinition
from reverse_hr.services.code_runner.domain.code_runner import (
    RunnerBase,
    finalize_runner_deletion,
    require_runner_mode,
    subject_lock,
)
from reverse_hr.services.code_runner.runner_readiness import fingerprint, require_execution_ready
from reverse_hr.services.code_runner.sandbox import CleanupUnconfirmed, SandboxUnavailable


class ValidationBatch(RunnerBase):
    __tablename__ = "validation_batches"
    validation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    plan: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ValidationAttempt(RunnerBase):
    __tablename__ = "validation_attempts"
    __table_args__ = (UniqueConstraint("validation_id", "ordinal"),)
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    validation_id: Mapped[str] = mapped_column(ForeignKey("validation_batches.validation_id"))
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int]
    node_id: Mapped[str] = mapped_column(String(36), index=True)
    scope_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ValidationCapture(RunnerBase):
    __tablename__ = "validation_captures"
    attempt_id: Mapped[str] = mapped_column(
        ForeignKey("validation_attempts.attempt_id"), primary_key=True
    )
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    capture: Mapped[dict] = mapped_column(JSON)
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def completed_prefix(session, row, plan):
    attempts = session.scalars(
        select(ValidationAttempt)
        .where(ValidationAttempt.validation_id == row.validation_id)
        .order_by(ValidationAttempt.ordinal)
    ).all()
    for ordinal, attempt in enumerate(attempts):
        if attempt.ordinal != ordinal or attempt.owner_id != row.owner_id:
            raise HTTPException(409)
        if attempt.state != "cleaned":
            return None
        stored = session.get(ValidationCapture, attempt.attempt_id)
        if stored is None or stored.owner_id != row.owner_id or ordinal >= len(plan.inputs):
            raise HTTPException(409)
        try:
            capture = CaseCapture.model_validate(stored.capture)
        except ValueError as exc:
            raise HTTPException(409) from exc
        item = plan.inputs[ordinal]
        if (
            str(capture.attempt_id) != attempt.attempt_id
            or capture.validation_id != plan.validation_id
            or capture.pin != plan.pin
            or capture.source_kind != item.source_kind
            or capture.source_key != item.source_key
            or capture.case_key != item.case_key
            or capture.manifest_digest != item.manifest_digest
            or capture.output.status not in {"executed", "runtime_error"}
        ):
            raise HTTPException(409)
    return len(attempts)


def register(engine, owner_id, access, suite: SuiteDefinition, plan: ValidationPlan):
    """Prepare only; signed reviewed-suite admission is still required before activation."""
    owner_id = UUID(str(owner_id))
    plan = ValidationPlan.model_validate(plan.model_dump(mode="json"))
    if plan != build_plan(suite, plan.pin, plan.validation_id):
        raise HTTPException(409)
    data = plan.model_dump(mode="json")
    with Session(engine) as session, session.begin():
        subject_lock(session, owner_id)
        access.check(owner_id)
        row = session.get(ValidationBatch, str(plan.validation_id))
        if row:
            if row.owner_id != str(owner_id) or row.plan != data:
                raise HTTPException(409)
        else:
            session.add(
                ValidationBatch(
                    validation_id=str(plan.validation_id),
                    owner_id=str(owner_id),
                    plan=data,
                    status="prepared",
                    created_at=datetime.now(UTC),
                )
            )
    return plan.validation_id


def stored_plan(row):
    if row.plan is None or row.status != "prepared":
        raise HTTPException(409)
    try:
        plan = ValidationPlan.model_validate(row.plan)
    except ValidationError as exc:
        raise HTTPException(409) from exc
    if str(plan.validation_id) != row.validation_id:
        raise HTTPException(409)
    return plan


def reserve(engine, owner_id, validation_id, access, node_id, executor):
    """Commit an obligation before a future caller may create any sandbox files."""
    owner_id, validation_id, node_id = (
        UUID(str(value)) for value in (owner_id, validation_id, node_id)
    )
    scope_id = executor.cleanup_scope()
    with Session(engine) as session, session.begin():
        subject_lock(session, owner_id)
        access.check(owner_id)
        row = session.get(ValidationBatch, str(validation_id))
        if row is None or row.owner_id != str(owner_id):
            raise HTTPException(404)
        plan = stored_plan(row)
        ordinal = completed_prefix(session, row, plan)
        if ordinal is None:
            return None
        if ordinal >= len(plan.inputs):
            raise HTTPException(409)
        require_runner_mode(session, "execution")
        attempt_id = uuid4()
        session.add(
            ValidationAttempt(
                attempt_id=str(attempt_id),
                validation_id=row.validation_id,
                owner_id=row.owner_id,
                ordinal=ordinal,
                node_id=str(node_id),
                scope_id=scope_id,
                state="reserved",
                created_at=datetime.now(UTC),
            )
        )
    return attempt_id


def bound(session, attempt_id, node_id, scope_id):
    row = session.get(ValidationAttempt, str(attempt_id), populate_existing=True)
    if (
        row is None
        or row.node_id != str(node_id)
        or row.scope_id != scope_id
        or row.state == "cleaned"
    ):
        raise HTTPException(409)
    return row


@contextmanager
def validation_scope(engine, access, admission, node_id, attempt_id, executor):
    """Executor caller holds this fence; leaving never erases cleanup duty."""
    node_id, attempt_id = UUID(str(node_id)), UUID(str(attempt_id))
    scope_id = executor.cleanup_scope()
    with executor.attempt_guard(attempt_id):
        require_execution_ready(executor)
        if str(executor.settings.runner_node_id) != str(node_id):
            raise SandboxUnavailable()
        with Session(engine) as session:
            attempt = bound(session, attempt_id, node_id, scope_id)
            owner = UUID(attempt.owner_id)
            row = session.get(ValidationBatch, attempt.validation_id)
            if row is None or row.owner_id != str(owner):
                raise HTTPException(409)
            plan = stored_plan(row)
            completed_prefix(session, row, plan)
            ordinal = attempt.ordinal
            if not 0 <= ordinal < len(plan.inputs):
                raise HTTPException(409)
        # Remote admission outside DB transaction. A permit must bind all plan
        # inputs as well as its suite pins, not merely the caller-supplied hash.
        if admission.check(owner, plan) is not None:
            raise HTTPException(409)
        if fingerprint(executor) != plan.pin.runtime_fingerprint:
            raise SandboxUnavailable()
        with Session(engine) as session, session.begin():
            subject_lock(session, owner)
            access.check(owner)
            attempt = bound(session, attempt_id, node_id, scope_id)
            row = session.get(ValidationBatch, attempt.validation_id)
            if (
                row is None
                or row.owner_id != str(owner)
                or attempt.owner_id != str(owner)
                or attempt.ordinal != ordinal
                or stored_plan(row) != plan
                or attempt.state != "reserved"
            ):
                raise HTTPException(409)
            attempt.state = "active"
            item = plan.inputs[attempt.ordinal].model_copy(deep=True)
        yield item


def recover_one(engine, node_id, executor, *, validation_id=None):
    """Own node/scope cleanup only. Lost output is never replayed as execution."""
    node_id = UUID(str(node_id))
    scope_id = executor.cleanup_scope()
    with Session(engine) as session:
        attempt_id = session.scalar(
            select(ValidationAttempt.attempt_id)
            .where(
                ValidationAttempt.node_id == str(node_id),
                ValidationAttempt.scope_id == scope_id,
                ValidationAttempt.state != "cleaned",
                *(
                    [ValidationAttempt.validation_id == str(validation_id)]
                    if validation_id is not None
                    else []
                ),
            )
            .order_by(ValidationAttempt.created_at)
            .limit(1)
        )
    if attempt_id is None:
        return False
    with executor.attempt_guard(attempt_id):
        with Session(engine) as session, session.begin():
            attempt = bound(session, attempt_id, node_id, scope_id)
            subject_lock(session, attempt.owner_id, allow_blocked=True)
            attempt.state = "cleaning"
        executor.cleanup_attempt(attempt_id)
        with Session(engine) as session, session.begin():
            attempt = bound(session, attempt_id, node_id, scope_id)
            subject = subject_lock(session, attempt.owner_id, allow_blocked=True)
            attempt.state = "cleaned"
            batch = session.get(ValidationBatch, attempt.validation_id)
            if batch is not None and not subject.blocked:
                batch.status = "interrupted"
            session.flush()
            if subject.blocked:
                finalize_runner_deletion(session, subject)
    return True


def stop_reason(engine, access, admission, attempt_id):
    """Fresh read-only gates; no Runner transaction spans the remote RPC."""
    try:
        with Session(engine) as session:
            attempt = session.get(ValidationAttempt, str(attempt_id))
            if attempt is None or attempt.state != "active":
                return "access_withdrawn"
            from reverse_hr.services.code_runner.domain.code_runner import RunnerSubject

            subject = session.get(RunnerSubject, attempt.owner_id)
            batch = session.get(ValidationBatch, attempt.validation_id)
            if (
                subject is None
                or subject.blocked
                or batch is None
                or batch.owner_id != attempt.owner_id
            ):
                return "access_withdrawn"
            plan, owner = stored_plan(batch), UUID(attempt.owner_id)
        access.check(owner)
        if admission.check(owner, plan) is not None:
            return "admission_unavailable"
        with Session(engine) as session:
            attempt = session.get(ValidationAttempt, str(attempt_id))
            subject = session.get(RunnerSubject, str(owner))
            batch = session.get(ValidationBatch, str(plan.validation_id))
            if (
                attempt is None
                or attempt.state != "active"
                or attempt.owner_id != str(owner)
                or subject is None
                or subject.blocked
                or batch is None
                or batch.owner_id != str(owner)
                or stored_plan(batch) != plan
            ):
                return "access_withdrawn"
        return None
    except HTTPException as exc:
        return "access_withdrawn" if exc.status_code in {404, 409} else "admission_unavailable"
    except Exception:
        return "admission_unavailable"


def stopped_output(reason):
    return (
        Output(status="cancelled", reason="access_withdrawn")
        if reason == "access_withdrawn"
        else Output(status="technical_error", reason="admission_unavailable")
    )


def execute_reserved(engine, access, admission, node_id, attempt_id, executor):
    """One bounded case; outputs publish only after double-confirmed cleanup."""
    from reverse_hr.services.code_runner.runner_monitor import StopMonitor

    with validation_scope(engine, access, admission, node_id, attempt_id, executor) as item:
        with Session(engine) as session:
            attempt = session.get(ValidationAttempt, str(attempt_id))
            batch = session.get(ValidationBatch, attempt.validation_id)
            plan = stored_plan(batch)
            if plan.inputs[attempt.ordinal] != item:
                raise HTTPException(409)
        with StopMonitor(lambda: stop_reason(engine, access, admission, attempt_id)) as monitor:
            try:
                outcome = executor.execute(
                    plan.format,
                    item.manifest.model_dump(mode="json"),
                    attempt_id=attempt_id,
                    stop_check=monitor.current,
                )
                output = Output.model_validate(
                    {
                        key: getattr(outcome, key)
                        for key in ("status", "stdout", "stderr", "exit_code", "reason")
                    }
                )
            except CleanupUnconfirmed:
                raise
            except Exception:
                output = Output(status="technical_error", reason="sandbox_failed")
            executor.cleanup_attempt(attempt_id)
            reason = monitor.current() or stop_reason(engine, access, admission, attempt_id)
            if reason:
                output = stopped_output(reason)
            return publish_capture(
                engine,
                access,
                node_id,
                attempt_id,
                executor.cleanup_scope(),
                plan,
                item,
                output,
                stop_check=monitor.current,
            )


def publish_capture(
    engine, access, node_id, attempt_id, scope_id, plan, item, output, *, stop_check=None
):
    """Internal to the fenced executor; caller has confirmed physical cleanup."""
    from reverse_hr.contracts.events import EventEnvelope
    from reverse_hr.shared.db import enqueue

    with Session(engine) as session, session.begin():
        attempt = bound(session, attempt_id, UUID(str(node_id)), scope_id)
        subject = subject_lock(session, attempt.owner_id, allow_blocked=True)
        batch = session.get(ValidationBatch, attempt.validation_id, populate_existing=True)
        if attempt.state != "active":
            raise HTTPException(409)
        if subject.blocked:
            attempt.state = "cleaned"
            session.flush()
            finalize_runner_deletion(session, subject)
            return None
        if (
            batch is None
            or batch.owner_id != attempt.owner_id
            or stored_plan(batch) != plan
            or not 0 <= attempt.ordinal < len(plan.inputs)
            or plan.inputs[attempt.ordinal] != item
        ):
            raise HTTPException(409)
        completed_prefix(session, batch, plan)
        try:
            access.check(UUID(attempt.owner_id))
        except HTTPException as exc:
            output = stopped_output(
                "access_withdrawn" if exc.status_code == 409 else "admission_unavailable"
            )
        if stop_check and (reason := stop_check()):
            output = stopped_output(reason)
        output = Output.model_validate(output.model_dump(mode="json"))
        capture = CaseCapture(
            validation_id=plan.validation_id,
            pin=plan.pin,
            attempt_id=UUID(attempt.attempt_id),
            source_kind=item.source_kind,
            source_key=item.source_key,
            case_key=item.case_key,
            manifest_digest=item.manifest_digest,
            output=output,
        )
        session.add(
            ValidationCapture(
                attempt_id=attempt.attempt_id,
                owner_id=attempt.owner_id,
                capture=capture.model_dump(mode="json"),
                completed_at=datetime.now(UTC),
            )
        )
        attempt.state = "cleaned"
        if output.status not in {"executed", "runtime_error"}:
            batch.status = "inconclusive"
        elif attempt.ordinal == len(plan.inputs) - 1:
            batch.status = "captures_ready"
        if batch.status != "prepared":
            enqueue(
                session,
                EventEnvelope(
                    event_type=f"code-runner.validation_{batch.status}.v1",
                    producer="code-runner",
                    aggregate_id=plan.validation_id,
                    aggregate_version=1,
                    correlation_id=plan.validation_id,
                    payload={
                        "candidate_id": UUID(batch.owner_id),
                        "validation_id": plan.validation_id,
                    },
                ),
            )
    return capture
