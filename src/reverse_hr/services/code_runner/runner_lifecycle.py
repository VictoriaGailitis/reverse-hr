"""Internal execution/result lifecycle. No service execution worker is enabled."""

from contextlib import contextmanager
from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.runner import Output
from reverse_hr.services.code_runner.domain.code_runner import (
    ExecutionAttempt,
    ExecutionResult,
    Job,
    RunnerSubject,
    cancel_pending,
    finalize_runner_deletion,
    manifest_for,
    reserve_attempt,
    run_event,
    subject_lock,
)


def bound_attempt(session, attempt_id, node_id, scope_id):
    row = session.get(ExecutionAttempt, str(attempt_id))
    if (
        row is None
        or row.node_id != str(node_id)
        or row.scope_id != scope_id
        or row.state == "cleaned"
    ):
        raise HTTPException(409)
    return row


@contextmanager
def execution_scope(engine, access, node_id, attempt_id, executor):
    """Fence late workers and recheck source admission while holding the OS lock.

    Only a future validated worker may call execute(attempt_id=...) inside this scope.
    Leaving it never erases the cleanup obligation, even when execute raises.
    """
    node_id, attempt_id = UUID(str(node_id)), UUID(str(attempt_id))
    scope_id = executor.cleanup_scope()
    with executor.attempt_guard(attempt_id):
        with Session(engine) as session, session.begin():
            attempt = bound_attempt(session, attempt_id, node_id, scope_id)
            subject_lock(session, attempt.candidate_id)
            session.refresh(attempt)
            if attempt.state != "reserved":
                raise HTTPException(409)
            row = session.get(Job, attempt.run_id)
            if row is None:
                raise HTTPException(409)
            manifest = manifest_for(access, row)
            if manifest is None:
                raise HTTPException(409)
            if row.cancel_requested or row.status != "pending_executor" or row.version != 1:
                raise HTTPException(409)
            attempt.state = "active"
            row.status, row.version = "running", 2
            run_event(session, row, "run_started")
        yield manifest


def recover_one(engine, node_id, executor):
    """Kill and clean one own-node attempt; confirm in DB only after cleanup returns.

    A failed/busy cleanup or database commit leaves a retryable durable obligation.
    Lease expiry is deliberately not used as evidence of physical cleanup.
    """
    node_id = UUID(str(node_id))
    scope_id = executor.cleanup_scope()
    with Session(engine) as session:
        attempt_id = session.scalar(
            select(ExecutionAttempt.attempt_id)
            .where(
                ExecutionAttempt.node_id == str(node_id),
                ExecutionAttempt.scope_id == scope_id,
                ExecutionAttempt.state != "cleaned",
            )
            .order_by(ExecutionAttempt.created_at)
            .limit(1)
        )
    if attempt_id is None:
        return False
    with executor.attempt_guard(attempt_id):
        with Session(engine) as session, session.begin():
            attempt = bound_attempt(session, attempt_id, node_id, scope_id)
            subject_lock(session, attempt.candidate_id, allow_blocked=True)
            session.refresh(attempt)
            if attempt.state == "cleaned":
                return False
            attempt.state = "cleaning"
        executor.cleanup_attempt(attempt_id)
        with Session(engine) as session, session.begin():
            attempt = bound_attempt(session, attempt_id, node_id, scope_id)
            subject = subject_lock(session, attempt.candidate_id, allow_blocked=True)
            session.refresh(attempt)
            attempt.state = "cleaned"
            session.flush()
            if subject.blocked:
                finalize_runner_deletion(session, subject)
            else:
                row = session.get(Job, attempt.run_id)
                if row is not None and row.status == "pending_executor" and row.cancel_requested:
                    cancel_pending(session, row)
                elif row is not None and row.status == "pending_executor":
                    row.status, row.error_code, row.version = (
                        "technical_error",
                        "executor_interrupted",
                        2,
                    )
                    run_event(session, row, "run_diagnosed")
                elif row is not None and row.status == "running":
                    store_result(
                        session,
                        row,
                        attempt,
                        Output(status="cancelled", reason="user_cancelled")
                        if row.cancel_requested
                        else Output(status="technical_error", reason="executor_interrupted"),
                    )
        return True


def store_result(session, row, attempt, output):
    """Called under subject lock after confirmed cleanup; result/event commit together."""
    if row.status != "running" or row.version != 2:
        raise HTTPException(409)
    session.add(
        ExecutionResult(
            run_id=row.run_id,
            candidate_id=row.candidate_id,
            attempt_id=attempt.attempt_id,
            completed_at=datetime.now(UTC),
            **output.model_dump(),
        )
    )
    row.status, row.error_code, row.version = output.status, output.reason, 3
    run_event(session, row, "run_cancelled" if output.status == "cancelled" else "run_finished")


def execute_reserved(engine, access, node_id, attempt_id, executor):
    """Orchestration for the opt-in worker after the readiness gate.

    The executor returns only after cleanup; a second idempotent cleanup check is
    required before publication. A crash loses in-memory output, never reexecutes it.
    """
    from reverse_hr.services.code_runner.runner_monitor import StopMonitor

    with execution_scope(engine, access, node_id, attempt_id, executor) as manifest:
        with StopMonitor(lambda: stop_reason(engine, access, attempt_id)) as monitor:
            return finish_execution(
                engine, access, node_id, attempt_id, executor, manifest, monitor
            )


def stop_reason(engine, access, attempt_id):
    # Do not hold DB locks/transactions across the remote signed source check.
    with Session(engine) as session:
        attempt = session.get(ExecutionAttempt, str(attempt_id))
        if attempt is None:
            return "access_withdrawn"
        subject = session.get(RunnerSubject, attempt.candidate_id)
        row = session.get(Job, attempt.run_id)
        if subject is None or subject.blocked or row is None:
            return "access_withdrawn"
        if row.cancel_requested:
            return "user_cancelled"
        session.expunge(row)
    return None if manifest_for(access, row) is not None else "access_withdrawn"


def finish_execution(engine, access, node_id, attempt_id, executor, manifest, monitor):
    from reverse_hr.services.code_runner.sandbox import CleanupUnconfirmed

    try:
        outcome = executor.execute(
            manifest.format, manifest.manifest, attempt_id=attempt_id, stop_check=monitor.current
        )
        data = {
            key: getattr(outcome, key)
            for key in ("status", "stdout", "stderr", "exit_code", "reason")
        }
        if data["status"] == "technical_error":
            data = {
                "status": "technical_error",
                "reason": "admission_unavailable"
                if data["reason"] == "admission_unavailable"
                else "sandbox_failed",
            }
        output = Output.model_validate(data)
    except CleanupUnconfirmed:
        raise
    except Exception:
        output = Output(status="technical_error", reason="sandbox_failed")
    executor.cleanup_attempt(attempt_id)
    with Session(engine) as session, session.begin():
        attempt = bound_attempt(session, attempt_id, UUID(str(node_id)), executor.cleanup_scope())
        subject = subject_lock(session, attempt.candidate_id, allow_blocked=True)
        session.refresh(attempt)
        if attempt.state != "active":
            raise HTTPException(409)
        attempt.state = "cleaned"
        session.flush()
        if subject.blocked:
            finalize_runner_deletion(session, subject)
            return False
        row = session.get(Job, attempt.run_id)
        if row is None:
            raise HTTPException(409)
        if row.cancel_requested:
            output = Output(status="cancelled", reason="user_cancelled")
        elif monitor.current() == "access_withdrawn" or manifest_for(access, row) is None:
            output = Output(status="cancelled", reason="access_withdrawn")
        elif monitor.current() == "admission_unavailable":
            output = Output(status="technical_error", reason="admission_unavailable")
        store_result(session, row, attempt, output)
    return True


def run_one(engine, access, executor):
    """One opt-in worker iteration: recover first, then claim once; never reexecute crashes."""
    from reverse_hr.services.code_runner.runner_readiness import require_execution_ready
    from reverse_hr.services.code_runner.sandbox import SandboxUnavailable

    require_execution_ready(executor)
    node_id = executor.settings.runner_node_id
    scope_id = executor.cleanup_scope()
    with Session(engine) as session:
        if session.scalar(
            select(ExecutionAttempt.attempt_id)
            .where(
                ExecutionAttempt.node_id == str(node_id),
                ExecutionAttempt.state != "cleaned",
                ExecutionAttempt.scope_id != scope_id,
            )
            .limit(1)
        ):
            raise SandboxUnavailable()
    if recover_one(engine, node_id, executor):
        return True
    attempt_id = reserve_attempt(engine, access, node_id, executor, required_mode="execution")
    if attempt_id is None:
        return False
    execute_reserved(engine, access, node_id, attempt_id, executor)
    return True
