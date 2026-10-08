"""Ordered idempotent board operations and a sealed immutable submission snapshot."""

import hashlib
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.market_cleanup import erase
from reverse_hr.market_state import lock
from reverse_hr.practical_common import emit, owned, receipt
from reverse_hr.processing_access import canonical
from reverse_hr.snapshot_access import SnapshotReceipt, SnapshotRequest


class BoardBase(DeclarativeBase):
    pass


class BoardSubject(BoardBase):
    __tablename__ = "board_subjects"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)


class Board(BoardBase):
    __tablename__ = "boards"
    __table_args__ = (UniqueConstraint("candidate_id", "session_id", "stage_id"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    stage_id: Mapped[str] = mapped_column(String(36))
    format: Mapped[str] = mapped_column(String(16), default="whiteboard")
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    state: Mapped[list] = mapped_column(JSON)


class BoardOperation(BoardBase):
    __tablename__ = "board_operations"
    __table_args__ = (UniqueConstraint("board_id", "version"),)
    operation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"))
    version: Mapped[int]
    command: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BoardSnapshot(BoardBase):
    __tablename__ = "board_snapshots"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    board_id: Mapped[str] = mapped_column(ForeignKey("boards.id"), unique=True)
    version: Mapped[int]
    state: Mapped[list] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))


class BoardNonce(BoardBase):
    __tablename__ = "board_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class BoardCreate(Contract):
    session_id: UUID
    stage_id: UUID


class Point(Contract):
    x: float = Field(ge=0, le=10000, allow_inf_nan=False)
    y: float = Field(ge=0, le=10000, allow_inf_nan=False)


class Shape(Contract):
    id: UUID
    kind: Literal["stroke", "rectangle", "ellipse", "text"]
    points: list[Point] = Field(min_length=1, max_length=500)
    text: str = Field(default="", max_length=2000)
    color: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    width: int = Field(default=2, ge=1, le=30)

    @model_validator(mode="after")
    def geometry(self):
        if (
            (self.kind in {"rectangle", "ellipse"} and len(self.points) != 2)
            or (self.kind == "text" and len(self.points) != 1)
            or (self.kind != "text" and self.text)
        ):
            raise ValueError("Invalid shape geometry")
        return self


class OperationCommand(Contract):
    operation_id: UUID
    action: Literal["put", "delete"]
    object_id: UUID
    shape: Shape | None = None

    @model_validator(mode="after")
    def binding(self):
        if (self.action == "put" and (self.shape is None or self.shape.id != self.object_id)) or (
            self.action == "delete" and self.shape is not None
        ):
            raise ValueError("Invalid board operation")
        return self


class BoardView(BoardCreate):
    board_id: UUID
    version: int
    status: Literal["editing", "sealed"]
    state: list[Shape]
    snapshot_id: UUID | None = None
    digest: str | None = None
    demo: Literal[True] = True


router = APIRouter(prefix="/v1/boards", tags=["whiteboard"])
internal_router = APIRouter(prefix="/internal/v1", tags=["internal-whiteboard"])


def guard(request, session, actor, ref, purpose="read"):
    return owned(request, session, actor, Board, BoardSubject, ref, purpose=purpose)


def view(session, row):
    session.flush()
    snap = session.scalar(select(BoardSnapshot).where(BoardSnapshot.board_id == row.id))
    return BoardView(
        board_id=row.id,
        session_id=row.session_id,
        stage_id=row.stage_id,
        version=row.version,
        status=row.status,
        state=row.state,
        snapshot_id=snap.id if snap else None,
        digest=snap.digest if snap else None,
    ).model_dump(mode="json")


@router.post("", response_model=BoardView, status_code=201)
def create(request: Request, actor: Actor, body: BoardCreate, idempotency: CommandKey):
    actor.require("candidate")

    def admit(session):
        lock(session, BoardSubject, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        if (
            request.app.state.stage_access.check_stage(
                actor.subject, body.session_id, body.stage_id
            )
            != "whiteboard"
        ):
            raise HTTPException(409)

    def change(session):
        row = Board(
            id=str(uuid4()),
            candidate_id=str(actor.subject),
            session_id=str(body.session_id),
            stage_id=str(body.stage_id),
            version=1,
            status="editing",
            state=[],
        )
        session.add(row)
        emit(session, request, row, "board_created")
        return {"id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "board_create",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=admit,
        present=lambda session, result: view(session, guard(request, session, actor, result["id"])),
    )


@router.get("/{board_id}", response_model=BoardView)
def get_board(request: Request, actor: Actor, board_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        return view(session, guard(request, session, actor, board_id))


@router.post("/{board_id}/operations", response_model=BoardView)
def operate(
    request: Request,
    actor: Actor,
    board_id: UUID,
    body: OperationCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(Board, str(board_id))
        if row.status != "editing":
            raise HTTPException(409)
        previous = session.get(BoardOperation, str(body.operation_id))
        payload = body.model_dump(mode="json")
        if previous:
            if (
                previous.board_id != row.id
                or previous.command != payload
                or previous.version != int(if_match.strip('"')) + 1
            ):
                raise HTTPException(409)
            return {"id": row.id}
        if row.version != int(if_match.strip('"')) or row.version >= 501:
            raise HTTPException(409)
        state = {shape["id"]: shape for shape in row.state}
        if body.action == "put":
            state[str(body.object_id)] = body.shape.model_dump(mode="json")
        elif str(body.object_id) not in state:
            raise HTTPException(409)
        else:
            del state[str(body.object_id)]
        output = [state[key] for key in sorted(state)]
        if (
            len(output) > 100
            or len(
                canonical(
                    BoardView(
                        board_id=row.id,
                        session_id=row.session_id,
                        stage_id=row.stage_id,
                        version=row.version,
                        status=row.status,
                        state=output,
                    )
                )
            )
            > 262144
        ):
            raise HTTPException(413)
        row.version += 1
        row.state = output
        session.add(
            BoardOperation(
                operation_id=str(body.operation_id),
                board_id=row.id,
                version=row.version,
                command=payload,
                received_at=datetime.now(UTC),
            )
        )
        emit(session, request, row, "board_changed")
        return {"id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"board_operation:{board_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=lambda session: guard(request, session, actor, board_id, "write"),
        present=lambda session, result: view(session, session.get(Board, result["id"])),
    )


@router.post("/{board_id}/seal", response_model=BoardView)
def seal(
    request: Request,
    actor: Actor,
    board_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(Board, str(board_id))
        if row.status != "editing" or row.version != int(if_match.strip('"')) or not row.state:
            raise HTTPException(409)
        row.status = "sealed"
        row.version += 1
        session.add(
            BoardSnapshot(
                id=str(uuid4()),
                board_id=row.id,
                version=row.version,
                state=row.state,
                digest=hashlib.sha256(canonical(BoardDocument(state=row.state))).hexdigest(),
            )
        )
        emit(session, request, row, "board_sealed")
        return {"id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"board_seal:{board_id}",
        idempotency,
        {"version": if_match},
        change,
        guard=lambda session: guard(request, session, actor, board_id, "write"),
        present=lambda session, result: view(session, session.get(Board, result["id"])),
    )


class BoardDocument(Contract):
    state: list[Shape] = Field(max_length=100)


@internal_router.post("/practical-receipt", response_model=SnapshotReceipt)
def snapshot_receipt(
    request: Request,
    body: SnapshotRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    def resolve(session, body):
        board = session.get(Board, str(body.workspace_id))
        snap = session.get(BoardSnapshot, str(body.snapshot_id))
        if (
            board
            and snap
            and board.status == "sealed"
            and snap.board_id == board.id
            and board.candidate_id == str(body.candidate_id)
            and board.session_id == str(body.session_id)
            and board.stage_id == str(body.stage_id)
        ):
            if (
                hashlib.sha256(canonical(BoardDocument(state=snap.state))).hexdigest()
                != snap.digest
            ):
                raise HTTPException(409)
            return {"format": "whiteboard", "snapshot_version": snap.version, "digest": snap.digest}

    return receipt(request, body, signature, BoardNonce, BoardSubject, resolve)


def process_deletion_request(session, event):
    def scrub(subject):
        ids = list(session.scalars(select(Board.id).where(Board.candidate_id == subject)))
        session.execute(delete(BoardOperation).where(BoardOperation.board_id.in_(ids)))
        session.execute(delete(BoardSnapshot).where(BoardSnapshot.board_id.in_(ids)))
        session.execute(delete(Board).where(Board.id.in_(ids)))

    return erase(session, event, "whiteboard", BoardSubject, scrub)
