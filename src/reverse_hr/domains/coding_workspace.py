"""Preparatory text snapshots and explicit run intents; never execute submitted code."""

import hashlib
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, delete, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import IdempotencyRecord, Outbox, consume_once, enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import canonical


class WorkspaceBase(DeclarativeBase):
    pass


class Workspace(WorkspaceBase):
    __tablename__ = "workspaces"
    __table_args__ = (UniqueConstraint("candidate_id", "session_id", "stage_id"),)
    workspace_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    stage_id: Mapped[str] = mapped_column(String(36))
    format: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]


class Snapshot(WorkspaceBase):
    __tablename__ = "workspace_snapshots"
    __table_args__ = (UniqueConstraint("workspace_id", "version"),)
    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    workspace_id: Mapped[str] = mapped_column(ForeignKey("workspaces.workspace_id"))
    version: Mapped[int]
    files: Mapped[list] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RunRequest(WorkspaceBase):
    __tablename__ = "workspace_runs"
    run_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(24), default="pending_runner")
    runner_version: Mapped[int] = mapped_column(default=0)
    snapshot_id: Mapped[str] = mapped_column(ForeignKey("workspace_snapshots.snapshot_id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class WorkspaceSubject(WorkspaceBase):
    __tablename__ = "workspace_subjects"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)


class File(Contract):
    path: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=65536)

    @field_validator("path")
    @classmethod
    def safe_path(cls, value):
        if (
            "\\" in value
            or not value.isascii()
            or any(ord(c) < 32 for c in value)
            or PurePosixPath(value).is_absolute()
            or str(PurePosixPath(value)) != value
            or any(part in {".", "..", ""} for part in value.split("/"))
        ):
            raise ValueError("Use a normalized relative path")
        return value


class FilesCommand(Contract):
    files: list[File] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def bounded(self):
        if (
            len({f.path for f in self.files}) != len(self.files)
            or any(len(f.content.encode("utf-8")) > 65536 for f in self.files)
            or sum(len(f.content.encode("utf-8")) for f in self.files) > 262144
        ):
            raise ValueError("Duplicate paths or oversized snapshot")
        return self


class CreateCommand(FilesCommand):
    session_id: UUID
    stage_id: UUID


class SnapshotView(FilesCommand):
    workspace_id: UUID
    snapshot_id: UUID
    version: int
    digest: str
    created_at: datetime
    format: Literal["code", "sql"]
    demo: Literal[True] = True
    phase: Literal["preflight"] = "preflight"


class RunCommand(Contract):
    snapshot_id: UUID


class RunView(Contract):
    run_id: UUID
    workspace_id: UUID
    snapshot_id: UUID
    snapshot_version: int
    status: Literal[
        "pending_runner",
        "pending_executor",
        "runner_diagnosed",
        "running",
        "runner_finished",
        "runner_cancelled",
    ] = "pending_runner"
    runner_status_path: str
    demo: Literal[True] = True


router = APIRouter(prefix="/v1", tags=["coding-workspace"])


def subject_lock(session, subject, *, allow_blocked=False):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(WorkspaceSubject)
        .values(subject=str(subject), blocked=False)
        .on_conflict_do_nothing(index_elements=["subject"])
    )
    row = session.scalar(
        select(WorkspaceSubject)
        .where(WorkspaceSubject.subject == str(subject))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.blocked and not allow_blocked:
        raise HTTPException(409)
    return row


def owned(session, actor, workspace_id):
    row = session.get(Workspace, str(workspace_id))
    if row is None or row.candidate_id != str(actor.subject):
        raise HTTPException(404)
    return row


def admit(request, actor, row, purpose="write"):
    kind = request.app.state.stage_access.check_stage(
        actor.subject, UUID(row.session_id), UUID(row.stage_id), purpose
    )
    if kind != row.format:
        raise HTTPException(409)


def view(row, snapshot):
    return SnapshotView(
        workspace_id=row.workspace_id,
        snapshot_id=snapshot.snapshot_id,
        version=snapshot.version,
        files=snapshot.files,
        digest=snapshot.digest,
        created_at=(
            snapshot.created_at.replace(tzinfo=UTC)
            if snapshot.created_at.tzinfo is None
            else snapshot.created_at.astimezone(UTC)
        ),
        format=row.format,
    ).model_dump(mode="json")


def emit(session, request, row, aggregate, version, kind, extra):
    enqueue(
        session,
        EventEnvelope(
            event_type=f"coding-workspace.{kind}.v1",
            producer="coding-workspace",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(aggregate),
            aggregate_version=version,
            payload={
                "workspace_id": UUID(row.workspace_id),
                "candidate_id": UUID(row.candidate_id),
                **extra,
            },
        ),
    )


def save(session, row, body, version):
    files = [f.model_dump() for f in sorted(body.files, key=lambda f: f.path)]
    snapshot = Snapshot(
        snapshot_id=str(uuid4()),
        workspace_id=row.workspace_id,
        version=version,
        files=files,
        digest=hashlib.sha256(canonical(FilesCommand(files=files))).hexdigest(),
        created_at=datetime.now(UTC),
    )
    session.add(snapshot)
    session.flush()
    return snapshot


@router.post("/workspaces", response_model=SnapshotView, status_code=201)
def create_workspace(request: Request, actor: Actor, body: CreateCommand, idempotency: CommandKey):
    actor.require("candidate")
    stage_format = None

    def guard(session):
        nonlocal stage_format
        subject_lock(session, actor.subject)
        stage_format = request.app.state.stage_access.check_stage(
            actor.subject, body.session_id, body.stage_id
        )

    def change(session):
        if session.scalar(
            select(Workspace.workspace_id).where(
                Workspace.candidate_id == str(actor.subject),
                Workspace.session_id == str(body.session_id),
                Workspace.stage_id == str(body.stage_id),
            )
        ):
            raise HTTPException(409)
        row = Workspace(
            workspace_id=str(uuid4()),
            candidate_id=str(actor.subject),
            session_id=str(body.session_id),
            stage_id=str(body.stage_id),
            format=stage_format,
            version=1,
        )
        session.add(row)
        session.flush()
        snapshot = save(session, row, body, 1)
        emit(
            session,
            request,
            row,
            row.workspace_id,
            1,
            "snapshot_saved",
            {"snapshot_id": UUID(snapshot.snapshot_id)},
        )
        return view(row, snapshot)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_workspace",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
    )


@router.put("/workspaces/{workspace_id}/files", response_model=SnapshotView)
def save_files(
    request: Request,
    actor: Actor,
    workspace_id: UUID,
    body: FilesCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def guard(session):
        subject_lock(session, actor.subject)
        admit(request, actor, owned(session, actor, workspace_id))

    def change(session):
        row = owned(session, actor, workspace_id)
        result = session.execute(
            update(Workspace)
            .where(Workspace.workspace_id == str(workspace_id), Workspace.version == expected)
            .values(version=expected + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(409)
        session.refresh(row)
        snapshot = save(session, row, body, row.version)
        emit(
            session,
            request,
            row,
            row.workspace_id,
            row.version,
            "snapshot_saved",
            {"snapshot_id": UUID(snapshot.snapshot_id)},
        )
        return view(row, snapshot)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"save_workspace:{workspace_id}",
        idempotency,
        {"body": body.model_dump(), "version": expected},
        change,
        guard=guard,
    )


@router.get("/workspaces/{workspace_id}", response_model=SnapshotView)
def get_latest(request: Request, actor: Actor, workspace_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = owned(session, actor, workspace_id)
        admit(request, actor, row, "read")
        snapshot = session.scalar(
            select(Snapshot).where(
                Snapshot.workspace_id == row.workspace_id, Snapshot.version == row.version
            )
        )
        return view(row, snapshot)


@router.get("/workspaces/{workspace_id}/snapshots/{snapshot_id}", response_model=SnapshotView)
def get_snapshot(request: Request, actor: Actor, workspace_id: UUID, snapshot_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = owned(session, actor, workspace_id)
        admit(request, actor, row, "read")
        snapshot = session.get(Snapshot, str(snapshot_id))
        if snapshot is None or snapshot.workspace_id != row.workspace_id:
            raise HTTPException(404)
        return view(row, snapshot)


def run_view(row, run, snapshot):
    return RunView(
        run_id=run.run_id,
        workspace_id=row.workspace_id,
        snapshot_id=snapshot.snapshot_id,
        snapshot_version=snapshot.version,
        status=run.status or "pending_runner",
        runner_status_path=f"/code-runner/v1/runs/{run.run_id}",
    ).model_dump(mode="json")


@router.post("/workspaces/{workspace_id}/runs", response_model=RunView, status_code=202)
def request_run(
    request: Request, actor: Actor, workspace_id: UUID, body: RunCommand, idempotency: CommandKey
):
    actor.require("candidate")

    def guard(session):
        subject_lock(session, actor.subject)
        admit(request, actor, owned(session, actor, workspace_id))

    def change(session):
        row = owned(session, actor, workspace_id)
        snapshot = session.get(Snapshot, str(body.snapshot_id))
        if snapshot is None or snapshot.workspace_id != row.workspace_id:
            raise HTTPException(404)
        run = RunRequest(
            run_id=str(uuid4()), snapshot_id=snapshot.snapshot_id, created_at=datetime.now(UTC)
        )
        session.add(run)
        emit(
            session,
            request,
            row,
            run.run_id,
            1,
            "run_requested",
            {"run_id": UUID(run.run_id), "snapshot_id": UUID(snapshot.snapshot_id)},
        )
        return run_view(row, run, snapshot)

    def present(session, result):
        row = owned(session, actor, workspace_id)
        run = session.get(RunRequest, result["run_id"])
        snapshot = session.get(Snapshot, run.snapshot_id) if run else None
        if snapshot is None or snapshot.workspace_id != row.workspace_id:
            raise HTTPException(404)
        return run_view(row, run, snapshot)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"request_run:{workspace_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        202,
        guard=guard,
        present=present,
    )


@router.get("/workspaces/{workspace_id}/runs/{run_id}", response_model=RunView)
def get_run(request: Request, actor: Actor, workspace_id: UUID, run_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = owned(session, actor, workspace_id)
        admit(request, actor, row)
        run = session.get(RunRequest, str(run_id))
        snapshot = session.get(Snapshot, run.snapshot_id) if run else None
        if snapshot is None or snapshot.workspace_id != row.workspace_id:
            raise HTTPException(404)
        return run_view(row, run, snapshot)


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
        first = row.request_id is None
        row.blocked, row.request_id = True, str(event.aggregate_id)
        workspaces = select(Workspace.workspace_id).where(Workspace.candidate_id == subject)
        snapshots = select(Snapshot.snapshot_id).where(Snapshot.workspace_id.in_(workspaces))
        session.execute(delete(RunRequest).where(RunRequest.snapshot_id.in_(snapshots)))
        session.execute(delete(Snapshot).where(Snapshot.workspace_id.in_(workspaces)))
        session.execute(delete(Workspace).where(Workspace.candidate_id == subject))
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == subject))
        session.execute(
            delete(Outbox).where(
                Outbox.envelope["producer"].as_string() == "coding-workspace",
                Outbox.envelope["payload"]["candidate_id"].as_string() == subject,
                Outbox.envelope["event_type"]
                .as_string()
                .in_(["coding-workspace.snapshot_saved.v1", "coding-workspace.run_requested.v1"]),
            )
        )
        if first:
            enqueue(
                session,
                EventEnvelope(
                    event_type="coding-workspace.data_deleted.v1",
                    producer="coding-workspace",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    aggregate_version=1,
                    payload=event.payload,
                ),
            )

    return consume_once(session, "coding-workspace.deletion_request", event, apply)


def process_runner_event(session, event):
    kinds = {
        "code-runner.run_accepted.v1": ({1}, "pending_executor"),
        "code-runner.run_diagnosed.v1": ({2}, "runner_diagnosed"),
        "code-runner.run_started.v1": ({2}, "running"),
        "code-runner.run_finished.v1": ({3}, "runner_finished"),
        "code-runner.run_cancelled.v1": ({2, 3}, "runner_cancelled"),
    }
    if (
        event.producer != "code-runner"
        or event.event_type not in kinds
        or set(event.payload) != {"candidate_id", "run_id", "workspace_id", "snapshot_id"}
        or event.aggregate_id != event.payload["run_id"]
        or event.aggregate_version not in kinds[event.event_type][0]
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = subject_lock(session, event.payload["candidate_id"], allow_blocked=True)
        if subject.blocked:
            return
        row = session.get(Workspace, str(event.payload["workspace_id"]))
        run = session.get(RunRequest, str(event.aggregate_id))
        snapshot = session.get(Snapshot, str(event.payload["snapshot_id"]))
        if (
            row is None
            or row.candidate_id != str(event.payload["candidate_id"])
            or run is None
            or run.snapshot_id != str(event.payload["snapshot_id"])
            or snapshot is None
            or snapshot.workspace_id != row.workspace_id
        ):
            raise HTTPException(409)
        if run.runner_version < event.aggregate_version:
            run.runner_version = event.aggregate_version
            run.status = kinds[event.event_type][1]

    return consume_once(session, "coding-workspace.runner_status", event, apply)
