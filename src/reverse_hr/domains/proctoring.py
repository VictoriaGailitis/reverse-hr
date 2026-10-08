"""Evidence of session integrity. Client telemetry never determines competence or AI use."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, ForeignKey, String, UniqueConstraint, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.db import consume_once, enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.market_cleanup import erase
from reverse_hr.market_state import NonceColumns, SubjectColumns, lock
from reverse_hr.processing_access import canonical

MAX_EVENTS = 20000
CLIENT_KINDS = Literal[
    "heartbeat",
    "visibility_hidden",
    "visibility_visible",
    "focus_lost",
    "focus_gained",
    "paste",
    "recording_started",
    "recording_stopped",
    "recording_error",
    "offline",
    "online",
    "telemetry_overflow",
]


class ProctorBase(DeclarativeBase):
    pass


class ProctorSubject(SubjectColumns, ProctorBase):
    __tablename__ = "proctor_subjects"


class ProctorNonce(NonceColumns, ProctorBase):
    __tablename__ = "proctor_nonces"


class IntegrityTrack(ProctorBase):
    __tablename__ = "integrity_tracks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    stage_id: Mapped[str] = mapped_column(String(36), unique=True)
    version: Mapped[int]
    timeline_version: Mapped[int]
    review_number: Mapped[int]


class ClientStream(ProctorBase):
    __tablename__ = "proctor_streams"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("integrity_tracks.id"), index=True)
    client_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ProctorEvent(ProctorBase):
    __tablename__ = "proctor_events"
    __table_args__ = (
        UniqueConstraint("track_id", "ordinal"),
        UniqueConstraint("stream_id", "sequence"),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("integrity_tracks.id"), index=True)
    ordinal: Mapped[int]
    source_key: Mapped[str | None] = mapped_column(String(64), unique=True)
    source: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(64))
    stream_id: Mapped[str | None] = mapped_column(ForeignKey("proctor_streams.id"))
    sequence: Mapped[int | None]
    client_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    elapsed_ms: Mapped[int | None]
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON)
    flags: Mapped[list] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))


class IntegrityReview(ProctorBase):
    __tablename__ = "integrity_reviews"
    __table_args__ = (UniqueConstraint("track_id", "number"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    track_id: Mapped[str] = mapped_column(ForeignKey("integrity_tracks.id"), index=True)
    number: Mapped[int]
    timeline_version: Mapped[int]
    evidence_digest: Mapped[str] = mapped_column(String(64))
    reviewer_id: Mapped[str] = mapped_column(String(36))
    outcome: Mapped[str] = mapped_column(String(20))
    reason: Mapped[str] = mapped_column(String(2000))
    evidence_ids: Mapped[list] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


class StreamCreate(Contract):
    session_id: UUID
    stage_id: UUID
    stream_id: UUID
    client_started_at: datetime

    @model_validator(mode="after")
    def aware(self):
        if self.client_started_at.tzinfo is None:
            raise ValueError("Timezone required")
        self.client_started_at = self.client_started_at.astimezone(UTC)
        return self


class ClientEvent(Contract):
    event_id: UUID
    sequence: int = Field(strict=True, ge=1, le=MAX_EVENTS)
    kind: CLIENT_KINDS
    client_time: datetime
    elapsed_ms: int = Field(strict=True, ge=0, le=86400000)

    @model_validator(mode="after")
    def aware(self):
        if self.client_time.tzinfo is None:
            raise ValueError("Timezone required")
        self.client_time = self.client_time.astimezone(UTC)
        return self


class EventBatch(Contract):
    events: list[ClientEvent] = Field(min_length=1, max_length=50)

    @model_validator(mode="after")
    def unique(self):
        if len({e.sequence for e in self.events}) != len(self.events) or len(
            {e.event_id for e in self.events}
        ) != len(self.events):
            raise ValueError("Duplicate event in batch")
        return self


class StreamView(Contract):
    track_id: UUID
    stream_id: UUID
    version: int
    timeline_version: int
    received_sequences: list[int]


class EventView(Contract):
    event_id: UUID
    ordinal: int
    source: str
    kind: str
    stream_id: UUID | None
    sequence: int | None
    client_time: datetime | None
    elapsed_ms: int | None
    occurred_at: datetime | None
    received_at: datetime
    details: dict
    flags: list[str]


class ReviewCommand(Contract):
    timeline_version: int = Field(strict=True, ge=0)
    evidence_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    outcome: Literal["clear", "inconclusive", "concern"]
    reason: str = Field(min_length=10, max_length=2000)
    evidence_ids: list[UUID] = Field(max_length=100)

    @model_validator(mode="after")
    def evidence(self):
        if not self.reason.strip() or len(set(self.evidence_ids)) != len(self.evidence_ids):
            raise ValueError("Invalid evidence")
        if self.outcome == "concern" and not self.evidence_ids:
            raise ValueError("Concern requires evidence")
        return self


class ReviewView(ReviewCommand):
    review_id: UUID
    number: int
    reviewer_id: UUID
    created_at: datetime


class StreamTiming(Contract):
    stream_id: UUID
    client_started_at: datetime
    server_received_at: datetime
    clock_or_delivery_offset_ms: int


class IntegritySummary(Contract):
    track_id: UUID | None
    candidate_id: UUID
    session_id: UUID
    stage_id: UUID
    version: int
    timeline_version: int
    status: Literal["no_material", "needs_review", "clear", "inconclusive", "concern"]
    evidence_digest: str
    flags: list[str]
    gaps: dict[str, list[list[int]]]
    streams: list[StreamTiming]
    latest_review: ReviewView | None
    client_telemetry_trusted: Literal[False] = False


class Timeline(Contract):
    summary: IntegritySummary
    events: list[EventView]
    next_after: int | None


router = APIRouter(prefix="/v1/proctoring", tags=["proctoring"])
internal_router = APIRouter(prefix="/internal/v1", tags=["internal-proctoring"])


def stage_guard(request, session, candidate, session_id, stage_id, purpose="read"):
    lock(session, ProctorSubject, candidate)
    request.app.state.processing_access.check(UUID(str(candidate)))
    return request.app.state.stage_access.check_stage(
        UUID(str(candidate)), UUID(str(session_id)), UUID(str(stage_id)), purpose
    )


def track(session, candidate, session_id, stage_id, create=False):
    row = session.scalar(select(IntegrityTrack).where(IntegrityTrack.stage_id == str(stage_id)))
    if row and (row.candidate_id != str(candidate) or row.session_id != str(session_id)):
        raise HTTPException(409)
    if row is None and create:
        row = IntegrityTrack(
            id=str(uuid4()),
            candidate_id=str(candidate),
            session_id=str(session_id),
            stage_id=str(stage_id),
            version=1,
            timeline_version=0,
            review_number=0,
        )
        session.add(row)
        session.flush()
    return row


def stream_view(session, row):
    head = session.get(IntegrityTrack, row.track_id)
    seqs = list(
        session.scalars(
            select(ProctorEvent.sequence)
            .where(ProctorEvent.stream_id == row.id)
            .order_by(ProctorEvent.sequence)
        )
    )
    return StreamView(
        track_id=head.id,
        stream_id=row.id,
        version=head.version,
        timeline_version=head.timeline_version,
        received_sequences=seqs,
    ).model_dump(mode="json")


@router.post("/streams", response_model=StreamView, status_code=201)
def create_stream(request: Request, actor: Actor, body: StreamCreate, idempotency: CommandKey):
    actor.require("candidate")

    def guard(session):
        # Existing streams may be recovered after submission, but new ones require active admission.
        old = session.get(ClientStream, str(body.stream_id))
        if old:
            head = session.get(IntegrityTrack, old.track_id)
            if head.candidate_id != str(actor.subject) or head.stage_id != str(body.stage_id):
                raise HTTPException(404)
        stage_guard(
            request,
            session,
            actor.subject,
            body.session_id,
            body.stage_id,
            "read" if old else "write",
        )

    def change(session):
        head = track(session, actor.subject, body.session_id, body.stage_id, True)
        old = session.get(ClientStream, str(body.stream_id))
        if old:
            if old.track_id != head.id or utc(old.client_started_at) != body.client_started_at:
                raise HTTPException(409)
        else:
            if (
                len(
                    list(
                        session.scalars(
                            select(ClientStream.id).where(ClientStream.track_id == head.id)
                        )
                    )
                )
                >= 64
            ):
                raise HTTPException(409)
            session.add(
                ClientStream(
                    id=str(body.stream_id),
                    track_id=head.id,
                    client_started_at=body.client_started_at,
                    received_at=datetime.now(UTC),
                )
            )
            head.version += 1
            session.flush()
        return {"stream_id": str(body.stream_id)}

    return execute(
        request.app.state.engine,
        actor.subject,
        "proctor_stream",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, result: stream_view(
            session, session.get(ClientStream, result["stream_id"])
        ),
    )


def owned_stream(request, session, actor, stream_id):
    actor.require("candidate")
    lock(session, ProctorSubject, actor.subject)
    row = session.get(ClientStream, str(stream_id))
    head = session.get(IntegrityTrack, row.track_id) if row else None
    if not head or head.candidate_id != str(actor.subject):
        raise HTTPException(404)
    stage_guard(request, session, actor.subject, head.session_id, head.stage_id)
    return row, head


@router.get("/streams/{stream_id}", response_model=StreamView)
def get_stream(request: Request, actor: Actor, stream_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row, _ = owned_stream(request, session, actor, stream_id)
        return stream_view(session, row)


def append(session, head, **values):
    if head.timeline_version >= MAX_EVENTS:
        raise HTTPException(409)
    head.timeline_version += 1
    head.version += 1
    session.add(ProctorEvent(track_id=head.id, ordinal=head.timeline_version, **values))
    session.flush()


@router.post("/streams/{stream_id}/events", response_model=StreamView)
def ingest(
    request: Request, actor: Actor, stream_id: UUID, body: EventBatch, idempotency: CommandKey
):
    def change(session):
        row, head = owned_stream(request, session, actor, stream_id)
        late = False
        try:
            stage_guard(request, session, actor.subject, head.session_id, head.stage_id, "write")
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            # Buffered evidence is accepted only for an already admitted stream, labelled late.
            stage_guard(request, session, actor.subject, head.session_id, head.stage_id)
            late = True
        now = datetime.now(UTC)
        for event in body.events:
            digest = hashlib.sha256(canonical(event)).hexdigest()
            old = session.scalar(
                select(ProctorEvent).where(
                    (ProctorEvent.id == str(event.event_id))
                    | (
                        (ProctorEvent.stream_id == row.id)
                        & (ProctorEvent.sequence == event.sequence)
                    )
                )
            )
            if old:
                if old.stream_id != row.id or old.id != str(event.event_id) or old.digest != digest:
                    raise HTTPException(409)
                continue
            flags = ["late_client_delivery"] if late else []
            if event.client_time > now + timedelta(seconds=30):
                flags.append("client_time_future")
            if (
                abs(
                    (event.client_time - utc(row.client_started_at)).total_seconds() * 1000
                    - event.elapsed_ms
                )
                > 10000
            ):
                flags.append("client_clock_discontinuity")
            previous = session.scalar(
                select(ProctorEvent).where(
                    ProctorEvent.stream_id == row.id, ProctorEvent.sequence == event.sequence - 1
                )
            )
            following = session.scalar(
                select(ProctorEvent).where(
                    ProctorEvent.stream_id == row.id, ProctorEvent.sequence == event.sequence + 1
                )
            )
            if (previous and previous.elapsed_ms > event.elapsed_ms) or (
                following and following.elapsed_ms < event.elapsed_ms
            ):
                flags.append("client_monotonic_discontinuity")
            append(
                session,
                head,
                id=str(event.event_id),
                source="client",
                kind=event.kind,
                stream_id=row.id,
                sequence=event.sequence,
                client_time=event.client_time,
                elapsed_ms=event.elapsed_ms,
                occurred_at=None,
                received_at=now,
                details={},
                flags=flags,
                digest=digest,
            )
        return {"stream_id": row.id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"proctor_events:{stream_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=lambda session: owned_stream(request, session, actor, stream_id),
        present=lambda session, result: stream_view(
            session, session.get(ClientStream, result["stream_id"])
        ),
    )


def summary(session, candidate, session_id, stage_id):
    head = track(session, candidate, session_id, stage_id)
    events = (
        list(
            session.scalars(
                select(ProctorEvent)
                .where(ProctorEvent.track_id == head.id)
                .order_by(ProctorEvent.ordinal)
            )
        )
        if head
        else []
    )
    gaps, flags = {}, {f for e in events for f in e.flags}
    for stream in (
        session.scalars(select(ClientStream).where(ClientStream.track_id == head.id))
        if head
        else []
    ):
        own = sorted((e for e in events if e.stream_id == stream.id), key=lambda e: e.sequence)
        ranges, next_seq = [], 1
        if not own:
            flags.add("client_stream_without_events")
        for e in own:
            if e.sequence > next_seq:
                ranges.append([next_seq, e.sequence - 1])
            next_seq = e.sequence + 1
        if ranges:
            gaps[stream.id] = ranges
        if any(b.elapsed_ms < a.elapsed_ms for a, b in zip(own, own[1:], strict=False)):
            flags.add("client_monotonic_discontinuity")
        if any(b.elapsed_ms - a.elapsed_ms > 90000 for a, b in zip(own, own[1:], strict=False)):
            flags.add("telemetry_time_gap")
    if gaps:
        flags.add("sequence_gap")
    if not any(e.source == "client" for e in events):
        flags.add("client_telemetry_missing")
    if any(e.kind in {"recording_error", "offline", "telemetry_overflow"} for e in events):
        flags.add("technical_issue")
    if any(
        e.kind in {"visibility_hidden", "focus_lost", "paste", "recording_stopped"} for e in events
    ):
        flags.add("attention_required")
    digests = [
        {
            "event_id": e.id,
            "digest": e.digest,
            "ordinal": e.ordinal,
            "received_at": utc(e.received_at).isoformat(),
            "flags": e.flags,
        }
        for e in events
    ]
    streams = (
        [
            {
                "stream_id": s.id,
                "client_started_at": utc(s.client_started_at).isoformat(),
                "received_at": utc(s.received_at).isoformat(),
            }
            for s in session.scalars(
                select(ClientStream)
                .where(ClientStream.track_id == head.id)
                .order_by(ClientStream.id)
            )
        ]
        if head
        else []
    )
    digest = hashlib.sha256(
        json.dumps(
            {"events": digests, "streams": streams}, sort_keys=True, separators=(",", ":")
        ).encode()
    ).hexdigest()
    timings = [
        StreamTiming(
            stream_id=s["stream_id"],
            client_started_at=s["client_started_at"],
            server_received_at=s["received_at"],
            clock_or_delivery_offset_ms=round(
                (
                    datetime.fromisoformat(s["received_at"])
                    - datetime.fromisoformat(s["client_started_at"])
                ).total_seconds()
                * 1000
            ),
        )
        for s in streams
    ]
    if any(abs(s.clock_or_delivery_offset_ms) > 30000 for s in timings):
        flags.add("client_clock_or_delivery_offset")
    if len(timings) > 1:
        flags.add("multiple_client_streams")
    review = (
        session.scalar(
            select(IntegrityReview).where(
                IntegrityReview.track_id == head.id, IntegrityReview.number == head.review_number
            )
        )
        if head and head.review_number
        else None
    )
    latest = (
        ReviewView(
            review_id=review.id,
            number=review.number,
            reviewer_id=review.reviewer_id,
            created_at=utc(review.created_at),
            timeline_version=review.timeline_version,
            evidence_digest=review.evidence_digest,
            outcome=review.outcome,
            reason=review.reason,
            evidence_ids=review.evidence_ids,
        )
        if review
        else None
    )
    return IntegritySummary(
        track_id=head.id if head else None,
        candidate_id=candidate,
        session_id=session_id,
        stage_id=stage_id,
        version=head.version if head else 0,
        timeline_version=head.timeline_version if head else 0,
        status=(
            review.outcome
            if review
            and review.timeline_version == head.timeline_version
            and review.evidence_digest == digest
            else "needs_review"
            if events
            else "no_material"
        ),
        evidence_digest=digest,
        flags=sorted(flags),
        gaps=gaps,
        streams=timings,
        latest_review=latest,
    )


def reviewer_guard(request, session, actor, candidate, session_id, stage_id):
    actor.require("assessment_reviewer", mfa=True)
    if actor.subject == candidate:
        raise HTTPException(403)
    for subject in sorted({str(candidate), str(actor.subject)}):
        lock(session, ProctorSubject, subject)
    stage_guard(request, session, candidate, session_id, stage_id)


@router.get(
    "/candidates/{candidate_id}/sessions/{session_id}/stages/{stage_id}", response_model=Timeline
)
def timeline(
    request: Request,
    actor: Actor,
    candidate_id: UUID,
    session_id: UUID,
    stage_id: UUID,
    after: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
):
    with Session(request.app.state.engine) as session, session.begin():
        if actor.subject == candidate_id:
            actor.require("candidate")
            stage_guard(request, session, candidate_id, session_id, stage_id)
        else:
            reviewer_guard(request, session, actor, candidate_id, session_id, stage_id)
        state = summary(session, candidate_id, session_id, stage_id)
        rows = list(
            session.scalars(
                select(ProctorEvent)
                .where(ProctorEvent.track_id == str(state.track_id), ProctorEvent.ordinal > after)
                .order_by(ProctorEvent.ordinal)
                .limit(limit + 1)
            )
        )
        views = [
            EventView(
                event_id=e.id,
                **{
                    key: utc(getattr(e, key))
                    if key in {"client_time", "occurred_at", "received_at"}
                    and getattr(e, key) is not None
                    else getattr(e, key)
                    for key in EventView.model_fields
                    if key != "event_id"
                },
            )
            for e in rows[:limit]
        ]
        return Timeline(
            summary=state, events=views, next_after=views[-1].ordinal if len(rows) > limit else None
        )


@router.post(
    "/candidates/{candidate_id}/sessions/{session_id}/stages/{stage_id}/reviews",
    response_model=IntegritySummary,
)
def review(
    request: Request,
    actor: Actor,
    candidate_id: UUID,
    session_id: UUID,
    stage_id: UUID,
    body: ReviewCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        reviewer_guard(request, session, actor, candidate_id, session_id, stage_id)

    def change(session):
        head = track(session, candidate_id, session_id, stage_id)
        state = summary(session, candidate_id, session_id, stage_id)
        if (
            not head
            or state.status == "no_material"
            or head.version != int(if_match.strip('"'))
            or (
                body.timeline_version != state.timeline_version
                or body.evidence_digest != state.evidence_digest
            )
        ):
            raise HTTPException(409)
        for ref in body.evidence_ids:
            event = session.get(ProctorEvent, str(ref))
            if not event or event.track_id != head.id:
                raise HTTPException(422)
        head.review_number += 1
        head.version += 1
        decision = IntegrityReview(
            id=str(uuid4()),
            track_id=head.id,
            number=head.review_number,
            reviewer_id=str(actor.subject),
            created_at=datetime.now(UTC),
            **body.model_dump(mode="json"),
        )
        session.add(decision)
        session.flush()
        enqueue(
            session,
            EventEnvelope(
                producer="proctoring",
                event_type="proctoring.integrity_reviewed.v1",
                correlation_id=request.state.trace_id,
                aggregate_id=UUID(head.id),
                aggregate_version=head.version,
                payload={
                    "candidate_id": candidate_id,
                    "session_id": session_id,
                    "stage_id": stage_id,
                    "review_id": UUID(decision.id),
                },
            ),
        )
        return {"candidate_id": str(candidate_id)}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"integrity_review:{stage_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: summary(session, candidate_id, session_id, stage_id).model_dump(
            mode="json"
        ),
    )


SERVER_KINDS = {
    "whiteboard.board_created.v1",
    "whiteboard.board_changed.v1",
    "whiteboard.board_sealed.v1",
    "media.recording_created.v1",
    "media.recording_restarted.v1",
    "media.recording_finalized.v1",
    "coding-workspace.snapshot_saved_observed.v1",
    "coding-workspace.run_requested_observed.v1",
}


def process_environment_event(session, event, processing, stages):
    if event.event_type not in SERVER_KINDS or event.producer != event.event_type.split(".")[0]:
        raise HTTPException(409)
    required = {"candidate_id", "session_id", "stage_id"}
    refs = (
        {"artifact_id"}
        if event.producer in {"whiteboard", "media"}
        else {"workspace_id", "snapshot_id"}
    )
    if event.event_type == "coding-workspace.run_requested_observed.v1":
        refs.add("run_id")
    if (
        set(event.payload) != required | refs
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(seconds=30)
    ):
        raise HTTPException(409)
    if event.aggregate_id != event.payload.get(
        "run_id", event.payload.get("artifact_id", event.payload.get("workspace_id"))
    ):
        raise HTTPException(409)

    def apply(session, event):
        candidate = event.payload["candidate_id"]
        restriction = lock(session, ProctorSubject, candidate, allow_blocked=True)
        if restriction.blocked:
            return
        try:
            processing.check(candidate)
            format = stages.check_stage(
                candidate, event.payload["session_id"], event.payload["stage_id"], "read"
            )
        except HTTPException as exc:
            if exc.status_code == 409:
                return
            raise
        if (
            format
            not in {
                "whiteboard": {"whiteboard"},
                "media": {"voice", "vcv"},
                "coding-workspace": {"code", "sql"},
            }[event.producer]
        ):
            raise HTTPException(409)
        head = track(
            session, candidate, event.payload["session_id"], event.payload["stage_id"], True
        )
        source_key = hashlib.sha256(
            f"{event.event_type}:{event.aggregate_id}:{event.aggregate_version}".encode()
        ).hexdigest()
        details = {key: str(event.payload[key]) for key in refs} | {
            "aggregate_version": event.aggregate_version
        }
        old = session.scalar(select(ProctorEvent).where(ProctorEvent.source_key == source_key))
        if old:
            if old.track_id != head.id or old.details != details:
                raise HTTPException(409)
            return
        append(
            session,
            head,
            id=str(event.event_id),
            source_key=source_key,
            source=event.producer,
            kind=event.event_type,
            stream_id=None,
            sequence=None,
            client_time=None,
            elapsed_ms=None,
            occurred_at=utc(event.occurred_at),
            received_at=datetime.now(UTC),
            details={key: str(event.payload[key]) for key in refs}
            | {"aggregate_version": event.aggregate_version},
            flags=[],
            digest=hashlib.sha256(canonical(event)).hexdigest(),
        )

    return consume_once(session, "proctoring.environment", event, apply)


def process_deletion_request(session, event):
    def scrub(subject):
        ids = list(
            session.scalars(select(IntegrityTrack.id).where(IntegrityTrack.candidate_id == subject))
        )
        session.execute(delete(IntegrityReview).where(IntegrityReview.track_id.in_(ids)))
        session.execute(delete(ProctorEvent).where(ProctorEvent.track_id.in_(ids)))
        session.execute(delete(ClientStream).where(ClientStream.track_id.in_(ids)))
        session.execute(delete(IntegrityTrack).where(IntegrityTrack.id.in_(ids)))
        # Reviewer deletion removes their free text without rewriting another candidate's evidence.
        session.execute(delete(IntegrityReview).where(IntegrityReview.reviewer_id == subject))

    return erase(session, event, "proctoring", ProctorSubject, scrub)
