"""Durable run intake and technical diagnostics; no untrusted host execution."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import DateTime, String, Text, delete, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import IdempotencyRecord, Outbox, consume_once, enqueue
from reverse_hr.events import EventEnvelope


class RunnerBase(DeclarativeBase):
    pass


class Job(RunnerBase):
    __tablename__ = "runner_jobs"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    workspace_id: Mapped[str] = mapped_column(String(36))
    snapshot_id: Mapped[str] = mapped_column(String(36))
    snapshot_version: Mapped[int]
    digest: Mapped[str] = mapped_column(String(64))
    format: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(24))
    error_code: Mapped[str | None] = mapped_column(String(32))
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    version: Mapped[int]
    correlation_id: Mapped[str] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunnerControl(RunnerBase):
    __tablename__ = "runner_control"
    control_id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str | None] = mapped_column(String(16))
    version: Mapped[int]


def require_runner_mode(session, mode):
    control = session.scalar(
        select(RunnerControl)
        .where(RunnerControl.control_id == 1)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if control is None:
        raise HTTPException(503)
    if control.mode is None:
        session.execute(
            update(RunnerControl)
            .where(RunnerControl.control_id == 1, RunnerControl.mode.is_(None))
            .values(mode=mode)
        )
        session.refresh(control)
        if control.mode != mode:
            raise HTTPException(409)
    elif control.mode != mode:
        raise HTTPException(409)
    return control


class RunnerSubject(RunnerBase):
    __tablename__ = "runner_subjects"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    deletion_status: Mapped[str | None] = mapped_column(String(16))
    deletion_correlation_id: Mapped[str | None] = mapped_column(String(36))


class ExecutionAttempt(RunnerBase):
    """Cleanup obligation committed before any files or process may be created."""

    __tablename__ = "runner_attempts"
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    run_id: Mapped[str] = mapped_column(String(36), unique=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    node_id: Mapped[str] = mapped_column(String(36), index=True)
    state: Mapped[str] = mapped_column(String(16))
    scope_id: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ExecutionResult(RunnerBase):
    __tablename__ = "runner_results"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    attempt_id: Mapped[str] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(24))
    stdout: Mapped[str] = mapped_column(Text)
    stderr: Mapped[str] = mapped_column(Text)
    exit_code: Mapped[int | None]
    reason: Mapped[str | None] = mapped_column(String(32))
    completed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Output(Contract):
    status: Literal["executed", "runtime_error", "limit_exceeded", "technical_error", "cancelled"]
    stdout: str = Field(default="", max_length=65536)
    stderr: str = Field(default="", max_length=65536)
    exit_code: int | None = Field(default=None, ge=-255, le=255, strict=True)
    reason: (
        Literal[
            "time_limit",
            "output_limit",
            "sandbox_failed",
            "executor_interrupted",
            "access_withdrawn",
            "user_cancelled",
            "admission_unavailable",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def coherent(self):
        try:
            size = len(self.stdout.encode("utf-8")) + len(self.stderr.encode("utf-8"))
        except UnicodeError as exc:
            raise ValueError("Invalid UTF-8 output") from exc
        if size > 65536:
            raise ValueError("Combined output exceeds limit")
        if self.status == "executed" and (self.exit_code != 0 or self.reason is not None):
            raise ValueError("Invalid successful exit")
        if self.status == "runtime_error" and (
            self.exit_code in (None, 0) or self.reason is not None
        ):
            raise ValueError("Invalid runtime exit")
        if self.status == "limit_exceeded" and self.reason not in {"time_limit", "output_limit"}:
            raise ValueError("Unconfirmed limit")
        if self.status in {"technical_error", "cancelled"}:
            if self.stdout or self.stderr or self.exit_code is not None:
                raise ValueError("Technical output must be redacted")
            allowed = (
                {"access_withdrawn", "user_cancelled"}
                if self.status == "cancelled"
                else {"sandbox_failed", "executor_interrupted", "admission_unavailable"}
            )
            if self.reason not in allowed:
                raise ValueError("Invalid technical reason")
        return self


class ResultView(Output):
    run_id: UUID
    workspace_id: UUID
    snapshot_id: UUID
    snapshot_version: int
    completed_at: datetime
    demo: Literal[True] = True


class JobView(Contract):
    run_id: UUID
    workspace_id: UUID
    snapshot_id: UUID
    snapshot_version: int
    status: Literal[
        "pending_executor",
        "running",
        "executed",
        "runtime_error",
        "limit_exceeded",
        "technical_error",
        "cancelled",
    ]
    error_code: (
        Literal[
            "executor_unavailable",
            "access_withdrawn",
            "user_cancelled",
            "admission_unavailable",
            "sandbox_failed",
            "executor_interrupted",
            "time_limit",
            "output_limit",
        ]
        | None
    )
    cancel_requested: bool
    version: int
    demo: Literal[True] = True


router = APIRouter(prefix="/v1", tags=["code-runner"])


def subject_lock(session, subject, *, allow_blocked=False):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(RunnerSubject)
        .values(subject=str(subject), blocked=False)
        .on_conflict_do_nothing(index_elements=["subject"])
    )
    row = session.scalar(
        select(RunnerSubject)
        .where(RunnerSubject.subject == str(subject))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.blocked and not allow_blocked:
        raise HTTPException(409)
    return row


def view(row):
    return JobView(
        run_id=row.run_id,
        workspace_id=row.workspace_id,
        snapshot_id=row.snapshot_id,
        snapshot_version=row.snapshot_version,
        status=row.status,
        error_code=row.error_code,
        version=row.version,
        cancel_requested=row.cancel_requested,
    ).model_dump(mode="json")


def manifest_for(access, row, purpose="write"):
    args = (UUID(row.candidate_id), UUID(row.run_id), UUID(row.workspace_id), UUID(row.snapshot_id))
    manifest = access.fetch(*args, "read") if purpose == "read" else access.fetch(*args)
    if manifest and (
        manifest.snapshot_version != row.snapshot_version
        or manifest.digest != row.digest
        or manifest.format != row.format
    ):
        raise HTTPException(503)
    return manifest


@router.get("/runs/{run_id}", response_model=JobView)
def get_job(request: Request, actor: Actor, run_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(Job, str(run_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        if manifest_for(request.app.state.manifest_access, row, "read") is None:
            raise HTTPException(409)
        return view(row)


@router.get("/runs/{run_id}/result", response_model=ResultView)
def get_result(request: Request, actor: Actor, run_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        job = session.get(Job, str(run_id))
        if job is None or job.candidate_id != str(actor.subject):
            raise HTTPException(404)
        if manifest_for(request.app.state.manifest_access, job, "read") is None:
            raise HTTPException(409)
        result = session.get(ExecutionResult, str(run_id))
        if result is None:
            raise HTTPException(404)
        completed_at = (
            result.completed_at.replace(tzinfo=UTC)
            if result.completed_at.tzinfo is None
            else result.completed_at
        )
        return ResultView(
            run_id=job.run_id,
            workspace_id=job.workspace_id,
            snapshot_id=job.snapshot_id,
            snapshot_version=job.snapshot_version,
            completed_at=completed_at,
            **{
                key: getattr(result, key)
                for key in ("status", "stdout", "stderr", "exit_code", "reason")
            },
        )


@router.post("/runs/{run_id}/cancel", response_model=JobView, status_code=202)
def cancel_job(
    request: Request, actor: Actor, run_id: UUID, idempotency: CommandKey, if_match: ExpectedVersion
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def owned(session):
        subject_lock(session, actor.subject)
        row = session.get(Job, str(run_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        return row

    def change(session):
        row = owned(session)
        if row.version != expected:
            raise HTTPException(409)
        if row.status not in {"pending_executor", "running"}:
            if row.status == "cancelled" and row.error_code == "user_cancelled":
                return view(row)
            raise HTTPException(409)
        row.cancel_requested = True
        active = session.scalar(
            select(ExecutionAttempt.attempt_id)
            .where(ExecutionAttempt.run_id == row.run_id, ExecutionAttempt.state != "cleaned")
            .limit(1)
        )
        if row.status == "pending_executor" and active is None:
            cancel_pending(session, row)
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"cancel_run:{run_id}",
        idempotency,
        {"version": expected},
        change,
        status=202,
        guard=owned,
        present=lambda session, _: view(owned(session)),
    )


def cancel_pending(session, row):
    if row.status != "pending_executor" or row.version != 1:
        raise HTTPException(409)
    row.status, row.error_code, row.version = "cancelled", "user_cancelled", 2
    run_event(session, row, "run_cancelled")


def run_event(session, row, kind):
    enqueue(
        session,
        EventEnvelope(
            event_type=f"code-runner.{kind}.v1",
            producer="code-runner",
            correlation_id=UUID(row.correlation_id),
            aggregate_id=UUID(row.run_id),
            aggregate_version=row.version,
            payload={
                key: UUID(getattr(row, key))
                for key in ("candidate_id", "run_id", "workspace_id", "snapshot_id")
            },
        ),
    )


def process_run_request(session, event, access):
    if (
        event.producer != "coding-workspace"
        or event.event_type != "coding-workspace.run_requested.v1"
        or set(event.payload) != {"candidate_id", "run_id", "workspace_id", "snapshot_id"}
        or event.aggregate_id != event.payload["run_id"]
        or event.aggregate_version != 1
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = subject_lock(session, event.payload["candidate_id"], allow_blocked=True)
        if subject.blocked:
            return
        existing = session.get(Job, str(event.aggregate_id))
        if existing:
            if any(getattr(existing, key) != str(event.payload[key]) for key in event.payload):
                raise HTTPException(409)
            return
        manifest = access.fetch(**event.payload)
        if manifest is None:
            return
        row = Job(
            run_id=str(event.aggregate_id),
            candidate_id=str(event.payload["candidate_id"]),
            workspace_id=str(event.payload["workspace_id"]),
            snapshot_id=str(event.payload["snapshot_id"]),
            snapshot_version=manifest.snapshot_version,
            digest=manifest.digest,
            format=manifest.format,
            status="pending_executor",
            error_code=None,
            version=1,
            correlation_id=str(event.correlation_id),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        enqueue(
            session,
            EventEnvelope(
                event_type="code-runner.run_accepted.v1",
                producer="code-runner",
                correlation_id=event.correlation_id,
                aggregate_id=event.aggregate_id,
                aggregate_version=1,
                payload=event.payload,
            ),
        )

    return consume_once(session, "code-runner.run_request", event, apply)


def diagnose_one(engine, access):
    """Without a validated isolated executor, report a technical failure, never a score.

    No subprocess, user files on disk, network inside submitted code or fallback interpreter.
    Fresh source admission is required even for this diagnostic transition.
    """
    with Session(engine) as session, session.begin():
        require_runner_mode(session, "diagnostic")
        candidate = session.scalar(
            select(Job.candidate_id)
            .where(
                Job.status == "pending_executor",
                ~select(ExecutionAttempt.attempt_id)
                .where(ExecutionAttempt.run_id == Job.run_id, ExecutionAttempt.state != "cleaned")
                .exists(),
            )
            .order_by(Job.created_at)
            .limit(1)
        )
        if candidate is None:
            return False
        subject = subject_lock(session, candidate, allow_blocked=True)
        row = session.scalar(
            select(Job)
            .where(
                Job.candidate_id == candidate,
                Job.status == "pending_executor",
                ~select(ExecutionAttempt.attempt_id)
                .where(ExecutionAttempt.run_id == Job.run_id, ExecutionAttempt.state != "cleaned")
                .exists(),
            )
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
            .execution_options(populate_existing=True)
        )
        if row is None:
            return False
        if subject.blocked:
            return False
        allowed = manifest_for(access, row) is not None
        row.status = "technical_error" if allowed else "cancelled"
        row.error_code = "executor_unavailable" if allowed else "access_withdrawn"
        row.version += 1
        enqueue(
            session,
            EventEnvelope(
                event_type="code-runner.run_diagnosed.v1",
                producer="code-runner",
                correlation_id=UUID(row.correlation_id),
                aggregate_id=UUID(row.run_id),
                aggregate_version=row.version,
                payload={
                    key: UUID(getattr(row, key))
                    for key in ("candidate_id", "run_id", "workspace_id", "snapshot_id")
                },
            ),
        )
        return True


def process_deletion_request(session, event):
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = str(event.payload["candidate_id"])
        row = subject_lock(session, subject, allow_blocked=True)
        if row.request_id and row.request_id != str(event.aggregate_id):
            raise HTTPException(409)
        row.blocked, row.request_id = True, str(event.aggregate_id)
        if row.deletion_correlation_id is None:
            row.deletion_correlation_id = str(event.correlation_id)
        finalize_runner_deletion(session, row)

    return consume_once(session, "code-runner.deletion_request", event, apply)


def finalize_runner_deletion(session, subject):
    """Physical cleanup is required; elapsed time or a dead lease proves nothing."""
    from reverse_hr.submitted_runner import SubmittedAttempt, SubmittedJob
    from reverse_hr.validation_lifecycle import (
        ValidationAttempt,
        ValidationBatch,
        ValidationCapture,
    )
    from reverse_hr.validation_queue import ValidationWork
    from reverse_hr.validation_verdict import VerdictRecord

    session.flush()
    pending = session.scalar(
        select(ExecutionAttempt.attempt_id)
        .where(
            ExecutionAttempt.candidate_id == subject.subject,
            ExecutionAttempt.state != "cleaned",
        )
        .limit(1)
    )
    validation_pending = session.scalar(
        select(ValidationAttempt.attempt_id)
        .where(
            ValidationAttempt.owner_id == subject.subject,
            ValidationAttempt.state != "cleaned",
        )
        .limit(1)
    )
    submitted_pending = session.scalar(
        select(SubmittedAttempt.attempt_id)
        .where(
            SubmittedAttempt.candidate_id == subject.subject, SubmittedAttempt.state != "cleaned"
        )
        .limit(1)
    )
    session.execute(delete(SubmittedJob).where(SubmittedJob.candidate_id == subject.subject))
    session.execute(
        update(SubmittedAttempt)
        .where(SubmittedAttempt.candidate_id == subject.subject)
        .values(outcome=None, capture=None)
    )
    # Erase private source immediately; keep metadata until physical cleanup.
    session.execute(
        update(ValidationBatch)
        .where(ValidationBatch.owner_id == subject.subject)
        .values(plan=None, status="withdrawn")
    )
    session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == subject.subject))
    session.execute(delete(ExecutionResult).where(ExecutionResult.candidate_id == subject.subject))
    session.execute(delete(ValidationCapture).where(ValidationCapture.owner_id == subject.subject))
    session.execute(delete(VerdictRecord).where(VerdictRecord.owner_id == subject.subject))
    session.execute(delete(ValidationWork).where(ValidationWork.owner_id == subject.subject))
    session.execute(delete(Job).where(Job.candidate_id == subject.subject))
    session.execute(
        delete(Outbox).where(
            Outbox.envelope["producer"].as_string() == "code-runner",
            Outbox.envelope["payload"]["candidate_id"].as_string() == subject.subject,
            Outbox.envelope["event_type"]
            .as_string()
            .in_(
                [
                    "code-runner.run_accepted.v1",
                    "code-runner.run_diagnosed.v1",
                    "code-runner.run_started.v1",
                    "code-runner.run_finished.v1",
                    "code-runner.run_cancelled.v1",
                    "code-runner.validation_captures_ready.v1",
                    "code-runner.validation_inconclusive.v1",
                    "code-runner.validation_verdict_recorded.v1",
                    "code-runner.validation_delivery_confirmed.v1",
                ]
            ),
        )
    )
    status = "restricted" if pending or validation_pending or submitted_pending else "deleted"
    if status == "deleted":
        session.execute(
            delete(SubmittedAttempt).where(SubmittedAttempt.candidate_id == subject.subject)
        )
        session.execute(
            delete(ExecutionAttempt).where(ExecutionAttempt.candidate_id == subject.subject)
        )
        session.execute(
            delete(ValidationAttempt).where(ValidationAttempt.owner_id == subject.subject)
        )
        session.execute(delete(ValidationBatch).where(ValidationBatch.owner_id == subject.subject))
    if subject.deletion_status != status:
        subject.deletion_status = status
        enqueue(
            session,
            EventEnvelope(
                event_type=f"code-runner.data_{status}.v1",
                producer="code-runner",
                correlation_id=UUID(subject.deletion_correlation_id),
                aggregate_id=UUID(subject.request_id),
                aggregate_version=1,
                payload={
                    "candidate_id": UUID(subject.subject),
                    "request_id": UUID(subject.request_id),
                },
            ),
        )


def reserve_attempt(engine, access, node_id, executor, *, required_mode=None):
    """Internal preparation only; no executor worker is enabled by this function."""
    node_id = str(UUID(str(node_id)))
    scope_id = executor.cleanup_scope()
    with Session(engine) as session, session.begin():
        if required_mode:
            require_runner_mode(session, required_mode)
        candidate = session.scalar(
            select(Job.candidate_id)
            .where(
                Job.status == "pending_executor",
                ~select(ExecutionAttempt.attempt_id)
                .where(ExecutionAttempt.run_id == Job.run_id)
                .exists(),
            )
            .order_by(Job.created_at)
            .limit(1)
        )
        if candidate is None:
            return None
        subject = subject_lock(session, candidate, allow_blocked=True)
        if subject.blocked:
            return None
        row = session.scalar(
            select(Job)
            .where(
                Job.candidate_id == candidate,
                Job.status == "pending_executor",
                ~select(ExecutionAttempt.attempt_id)
                .where(ExecutionAttempt.run_id == Job.run_id)
                .exists(),
            )
            .order_by(Job.created_at)
            .with_for_update(skip_locked=True)
        )
        if row is None or manifest_for(access, row) is None:
            return None
        attempt_id = uuid4()
        session.add(
            ExecutionAttempt(
                attempt_id=str(attempt_id),
                run_id=row.run_id,
                candidate_id=candidate,
                node_id=node_id,
                scope_id=scope_id,
                state="reserved",
                created_at=datetime.now(UTC),
            )
        )
        return attempt_id
