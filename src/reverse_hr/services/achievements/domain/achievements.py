"""Source-scoped achievements, verified bindings, revisions and consent-gated visibility."""

from datetime import UTC, date, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.protocols.exchange import ExchangeReceipt, ExchangeRequest, respond
from reverse_hr.protocols.market_access import Signature
from reverse_hr.protocols.market_state import NonceColumns, SubjectColumns, lock
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord, Outbox, consume_once, enqueue


class AchievementsBase(DeclarativeBase):
    pass


class AchievementSubject(SubjectColumns, AchievementsBase):
    __tablename__ = "achievement_subjects"


class AchievementNonce(NonceColumns, AchievementsBase):
    __tablename__ = "achievement_nonces"


class SourceRow(AchievementsBase):
    __tablename__ = "achievement_sources"
    source_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    key: Mapped[str] = mapped_column(String(64), unique=True)
    adapter: Mapped[str] = mapped_column(String(24))
    name: Mapped[str] = mapped_column(String(100))
    partner_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    enabled: Mapped[bool]
    version: Mapped[int]


class Connection(AchievementsBase):
    __tablename__ = "achievement_connections"
    __table_args__ = (
        UniqueConstraint("source_id", "external_account"),
        UniqueConstraint("candidate_id", "source_id"),
    )
    connection_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    external_account: Mapped[str | None] = mapped_column(String(128))
    consent_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_sync_status: Mapped[str | None] = mapped_column(String(24))


class AchievementRow(AchievementsBase):
    __tablename__ = "achievements"
    __table_args__ = (UniqueConstraint("source_id", "external_id"),)
    achievement_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    external_id: Mapped[str] = mapped_column(String(128))
    connection_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    external_version: Mapped[int]
    version: Mapped[int]
    status: Mapped[str] = mapped_column(String(24))
    demo: Mapped[bool]
    published: Mapped[bool]
    publication_consent_id: Mapped[str | None] = mapped_column(String(36))
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AchievementHistory(AchievementsBase):
    __tablename__ = "achievement_history"
    history_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    achievement_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int]
    action: Mapped[str] = mapped_column(String(24))
    reason: Mapped[str | None] = mapped_column(String(2000))
    snapshot: Mapped[dict] = mapped_column(JSON)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ImportJob(AchievementsBase):
    __tablename__ = "achievement_imports"
    import_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    source_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    records: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24))
    results: Mapped[list] = mapped_column(JSON)


class SourceEnabled(Contract):
    enabled: bool = Field(strict=True)


class SourceCreate(Contract):
    key: str = Field(pattern=r"^[a-z][a-z0-9-]{1,63}$")
    name: str = Field(min_length=1, max_length=100)
    adapter: Literal["partner", "demo-fsp", "demo-hackathon-platform"]
    partner_id: UUID | None = None

    @model_validator(mode="after")
    def binding(self):
        if (self.adapter == "partner") != (self.partner_id is not None):
            raise ValueError("Partner identity required only for partner sources")
        return self


class AchievementFields(Contract):
    event: str = Field(min_length=1, max_length=200)
    discipline: str = Field(min_length=1, max_length=100)
    occurred_on: date
    specialization: str | None = Field(default=None, min_length=1, max_length=100)
    format: Literal["individual", "team"]
    place: int | None = Field(default=None, strict=True, ge=1, le=1000000)
    points: int | None = Field(default=None, strict=True, ge=0, le=1000000000)
    group_size: int | None = Field(default=None, strict=True, ge=1, le=1000000)
    evidence_url: str | None = Field(default=None, max_length=500, pattern=r"^https://[^\s]+$")

    @model_validator(mode="after")
    def placement(self):
        if self.place and self.group_size and self.place > self.group_size:
            raise ValueError("Place exceeds group size")
        return self


class ImportedRecord(AchievementFields):
    external_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    external_account: str = Field(min_length=1, max_length=128)
    external_version: int = Field(strict=True, ge=1)
    revoked: bool = Field(default=False, strict=True)


class Declaration(AchievementFields):
    consent_id: UUID


class ImportCommand(Contract):
    records: list[ImportedRecord] = Field(min_length=1, max_length=100)


class ConnectCommand(Contract):
    source_id: UUID
    consent_id: UUID


class LinkConfirmation(Contract):
    connection_id: UUID
    external_account: str = Field(min_length=1, max_length=128)


class Visibility(Contract):
    published: bool = Field(strict=True)
    consent_id: UUID | None = None

    @model_validator(mode="after")
    def permission(self):
        if self.published != (self.consent_id is not None):
            raise ValueError("Publication requires a separate consent")
        return self


class HumanReview(Contract):
    status: Literal["confirmed", "revoked"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class SourceView(Contract):
    source_id: UUID
    key: str
    name: str
    adapter: Literal["self", "partner", "demo-fsp", "demo-hackathon-platform"]
    demo: bool
    enabled: bool
    version: int
    capabilities: list[str]


class ConnectionView(Contract):
    connection_id: UUID
    candidate_id: UUID
    source_id: UUID
    status: Literal["pending", "active", "disconnected"]
    external_account: str | None
    version: int
    last_synced_at: datetime | None
    last_sync_status: str | None


class AchievementView(Contract):
    achievement_id: UUID
    candidate_id: UUID
    source_id: UUID
    external_id: str
    status: Literal["declared", "imported_pending", "confirmed", "revoked"]
    demo: bool
    published: bool
    version: int
    external_version: int
    synced_at: datetime
    result: ImportedRecord


class ImportView(Contract):
    import_id: UUID
    status: Literal["pending", "completed", "partial_failure", "failed"]
    results: list[dict] = Field(default_factory=list)


class HistoryView(Contract):
    version: int
    action: str
    reason: str | None
    snapshot: AchievementView
    at: datetime


router = APIRouter(prefix="/v1", tags=["achievements"])
internal_router = APIRouter(prefix="/internal/v1/exchange", tags=["internal-achievements"])


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def allowed_source(request, source):
    if source is None or not source.enabled:
        raise HTTPException(409, "Source disabled")
    if source.adapter.startswith("demo-") and request.app.state.settings.deployment_mode != "demo":
        raise HTTPException(409, "Demo source unavailable in production")


def fence(request, session, candidate):
    lock(session, AchievementSubject, candidate)
    request.app.state.processing_access.check(UUID(str(candidate)))


def consent(request, candidate, consent_id, purpose):
    request.app.state.market_access.require(
        "privacy",
        "purpose-permission",
        candidate_id=UUID(str(candidate)),
        consent_id=UUID(str(consent_id)),
        consent_purpose=purpose,
    )


def connection_for(request, session, key, candidate):
    row = session.get(Connection, str(key))
    if row is None or row.candidate_id != str(candidate):
        raise HTTPException(404)
    fence(request, session, candidate)
    allowed_source(request, session.get(SourceRow, row.source_id))
    if row.status != "active":
        raise HTTPException(409, "Verified active binding required")
    consent(request, candidate, row.consent_id, "achievement_import")
    return row


def source_view(row):
    return dict(
        source_id=row.source_id,
        key=row.key,
        name=row.name,
        adapter=row.adapter,
        demo=row.adapter.startswith("demo-"),
        enabled=row.enabled,
        version=row.version,
        capabilities=["declare", "visibility", "disconnect", "versions"]
        if row.adapter == "self"
        else ["link", "sync", "disconnect", "versions", "revoke"],
    )


def connection_view(row):
    return dict(
        connection_id=row.connection_id,
        candidate_id=row.candidate_id,
        source_id=row.source_id,
        status=row.status,
        external_account=row.external_account,
        version=row.version,
        last_synced_at=utc(row.last_synced_at).isoformat() if row.last_synced_at else None,
        last_sync_status=row.last_sync_status,
    )


def achievement_view(row):
    return dict(
        achievement_id=row.achievement_id,
        candidate_id=row.candidate_id,
        source_id=row.source_id,
        external_id=row.external_id,
        status=row.status,
        demo=row.demo,
        published=row.published,
        version=row.version,
        external_version=row.external_version,
        synced_at=utc(row.synced_at).isoformat(),
        result=row.data,
    )


def history(session, request, row, actor, kind, reason=None):
    session.add(
        AchievementHistory(
            history_id=str(uuid4()),
            achievement_id=row.achievement_id,
            candidate_id=row.candidate_id,
            actor_id=str(actor),
            version=row.version,
            action=kind,
            reason=reason,
            snapshot=achievement_view(row),
            at=datetime.now(UTC),
        )
    )
    enqueue(
        session,
        EventEnvelope(
            producer="achievements",
            event_type="achievements.achievement_changed.v1",
            aggregate_id=UUID(row.achievement_id),
            aggregate_version=row.version,
            correlation_id=request.state.trace_id,
            payload={
                "candidate_id": UUID(row.candidate_id),
                "achievement_id": UUID(row.achievement_id),
            },
        ),
    )


def partner(request, session, actor):
    actor.require("achievement_partner")
    row = session.scalar(select(SourceRow).where(SourceRow.partner_id == str(actor.subject)))
    allowed_source(request, row)
    request.app.state.processing_access.check(actor.subject)
    return row


def partner_fences(request, session, actor, accounts):
    source = partner(request, session, actor)
    rows = list(
        session.scalars(
            select(Connection).where(
                Connection.source_id == source.source_id, Connection.external_account.in_(accounts)
            )
        )
    )
    for subject in sorted({str(actor.subject)} | {row.candidate_id for row in rows}):
        fence(request, session, subject)
    return source


@router.get("/achievement-sources", response_model=list[SourceView])
def sources(request: Request):
    with Session(request.app.state.engine) as session:
        rows = session.scalars(select(SourceRow).order_by(SourceRow.key))
        return [
            source_view(row)
            for row in rows
            if request.app.state.settings.deployment_mode == "demo" or row.adapter == "partner"
        ]


@router.post("/achievement-sources", response_model=SourceView, status_code=201)
def create_source(request: Request, actor: Actor, body: SourceCreate, idempotency: CommandKey):
    actor.require("integration_admin", mfa=True)

    def change(session):
        fence(request, session, actor.subject)
        row = SourceRow(
            source_id=str(uuid4()), **body.model_dump(mode="json"), enabled=True, version=1
        )
        allowed_source(request, row)
        session.add(row)
        return source_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_source",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: fence(request, session, actor.subject),
    )


@router.put("/achievement-sources/{source_id}/enabled", response_model=SourceView)
def enable_source(
    request: Request,
    actor: Actor,
    source_id: UUID,
    body: SourceEnabled,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("integration_admin", mfa=True)

    def change(session):
        row = session.scalar(
            select(SourceRow)
            .where(SourceRow.source_id == str(source_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise HTTPException(404)
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.enabled, row.version = body.enabled, row.version + 1
        return source_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_source_enabled:" + str(source_id),
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
        change,
        guard=lambda session: fence(request, session, actor.subject),
        present=lambda session, _: source_view(session.get(SourceRow, str(source_id))),
    )


@router.post("/achievement-connections", response_model=ConnectionView, status_code=201)
def connect(request: Request, actor: Actor, body: ConnectCommand, idempotency: CommandKey):
    actor.require("candidate")

    def guard(session):
        fence(request, session, actor.subject)
        allowed_source(request, session.get(SourceRow, str(body.source_id)))
        consent(request, actor.subject, body.consent_id, "achievement_import")

    def change(session):
        source = session.get(SourceRow, str(body.source_id))
        row = session.scalar(
            select(Connection).where(
                Connection.source_id == str(body.source_id),
                Connection.candidate_id == str(actor.subject),
            )
        )
        if row and row.status != "disconnected":
            raise HTTPException(409, "Connection already exists")
        if row is None:
            row = Connection(
                connection_id=str(uuid4()),
                candidate_id=str(actor.subject),
                source_id=str(body.source_id),
                version=0,
            )
            session.add(row)
        row.status = (
            "active"
            if source.adapter.startswith("demo-") or source.adapter == "self"
            else "pending"
        )
        row.external_account = str(actor.subject) if row.status == "active" else None
        row.consent_id, row.version = str(body.consent_id), row.version + 1
        row.expires_at = datetime.now(UTC) + timedelta(minutes=10)
        return {"connection_id": row.connection_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_connect",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, result: connection_view(
            session.get(Connection, result["connection_id"])
        ),
    )


@router.post("/achievement-link-confirmations", response_model=ConnectionView)
def confirm_link(
    request: Request,
    actor: Actor,
    body: LinkConfirmation,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        source = partner(request, session, actor)
        row = session.get(Connection, str(body.connection_id))
        if row is None or row.source_id != source.source_id:
            raise HTTPException(404)
        for subject in sorted({str(actor.subject), row.candidate_id}):
            fence(request, session, subject)
        consent(request, row.candidate_id, row.consent_id, "achievement_import")

    def change(session):
        row = session.get(Connection, str(body.connection_id))
        if (
            row.status != "pending"
            or row.version != int(if_match.strip('"'))
            or utc(row.expires_at) <= datetime.now(UTC)
        ):
            raise HTTPException(409)
        row.external_account, row.status, row.version = (
            body.external_account,
            "active",
            row.version + 1,
        )
        return connection_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_confirm_link:" + str(body.connection_id),
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
        change,
        guard=guard,
    )


@router.get("/achievement-connections/me", response_model=list[ConnectionView])
def my_connections(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        fence(request, session, actor.subject)
        return [
            connection_view(row)
            for row in session.scalars(
                select(Connection)
                .where(Connection.candidate_id == str(actor.subject))
                .order_by(Connection.connection_id)
                .limit(100)
            )
        ]


@router.post("/achievement-connections/{connection_id}/disconnect", response_model=ConnectionView)
def disconnect(
    request: Request,
    actor: Actor,
    connection_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")

    def guard(session):
        row = session.get(Connection, str(connection_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        fence(request, session, actor.subject)

    def change(session):
        row = session.get(Connection, str(connection_id))
        if row.version != int(if_match.strip('"')) or row.status == "disconnected":
            raise HTTPException(409)
        row.status, row.version, row.external_account = "disconnected", row.version + 1, None
        for item in session.scalars(
            select(AchievementRow).where(AchievementRow.connection_id == row.connection_id)
        ):
            item.published, item.publication_consent_id, item.version = (
                False,
                None,
                item.version + 1,
            )
            history(session, request, item, actor.subject, "disconnected")
        return connection_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_disconnect:" + str(connection_id),
        idempotency,
        {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: connection_view(session.get(Connection, str(connection_id))),
    )


def apply_record(request, session, source, record, actor):
    binding = session.scalar(
        select(Connection).where(
            Connection.source_id == source.source_id,
            Connection.external_account == record.external_account,
        )
    )
    if binding is None:
        raise HTTPException(409, "External account is not bound")
    connection_for(request, session, binding.connection_id, binding.candidate_id)
    key = record.external_id
    row = session.scalar(
        select(AchievementRow).where(
            AchievementRow.source_id == source.source_id, AchievementRow.external_id == key
        )
    )
    data = record.model_dump(mode="json")
    if row:
        if row.candidate_id != binding.candidate_id or row.connection_id != binding.connection_id:
            raise HTTPException(409, "Cannot reassign achievement ownership")
        if record.external_version < row.external_version:
            return dict(external_id=key, status="stale")
        if record.external_version == row.external_version:
            if row.data != data:
                raise HTTPException(409, "Same source version has conflicting data")
            return dict(external_id=key, status="duplicate", achievement_id=row.achievement_id)
    else:
        row = AchievementRow(
            achievement_id=str(uuid4()),
            source_id=source.source_id,
            external_id=key,
            connection_id=binding.connection_id,
            candidate_id=binding.candidate_id,
            version=0,
            published=False,
            publication_consent_id=None,
        )
        session.add(row)
    row.data, row.external_version, row.version = data, record.external_version, row.version + 1
    row.status = (
        "revoked"
        if record.revoked
        else "confirmed"
        if source.adapter.startswith("demo-")
        else "imported_pending"
    )
    row.demo, row.synced_at = (
        request.app.state.settings.deployment_mode == "demo",
        datetime.now(UTC),
    )
    history(session, request, row, actor, "revoked" if record.revoked else "imported")
    return dict(external_id=key, status="applied", achievement_id=row.achievement_id)


def apply_batch(request, session, source, records, actor):
    # Acquire all candidate fences in one order before applying any row.
    accounts = {record.external_account for record in records}
    bindings = list(
        session.scalars(
            select(Connection).where(
                Connection.source_id == source.source_id, Connection.external_account.in_(accounts)
            )
        )
    )
    for subject in sorted({str(actor)} | {row.candidate_id for row in bindings}):
        fence(request, session, subject)
    results = []
    for record in records:
        try:
            with session.begin_nested():
                results.append(apply_record(request, session, source, record, actor))
        except HTTPException as exc:
            if exc.status_code == 503:
                raise
            results.append(
                dict(external_id=record.external_id, status="error", code=exc.status_code)
            )
    return results


@router.put("/achievements/{external_id}")
def partner_put(
    request: Request, actor: Actor, external_id: str, body: ImportedRecord, idempotency: CommandKey
):
    if external_id != body.external_id:
        raise HTTPException(422)

    def guard(session):
        partner_fences(request, session, actor, {body.external_account})

    def change(session):
        source = partner(request, session, actor)
        return apply_record(request, session, source, body, actor.subject)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_put:" + external_id,
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=guard,
    )


@router.post("/achievement-imports", response_model=ImportView, status_code=202)
def submit_import(request: Request, actor: Actor, body: ImportCommand, idempotency: CommandKey):
    def guard(session):
        partner_fences(request, session, actor, {item.external_account for item in body.records})

    def change(session):
        source = partner(request, session, actor)
        if (
            len(
                list(
                    session.scalars(
                        select(ImportJob.import_id)
                        .where(
                            ImportJob.created_by == str(actor.subject),
                            ImportJob.status == "pending",
                        )
                        .limit(10)
                    )
                )
            )
            >= 10
        ):
            raise HTTPException(409, "Pending import quota reached")
        row = ImportJob(
            import_id=str(uuid4()),
            source_id=source.source_id,
            created_by=str(actor.subject),
            records=body.model_dump(mode="json")["records"],
            status="pending",
            results=[],
        )
        session.add(row)
        return dict(import_id=row.import_id, status=row.status)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_import",
        idempotency,
        body.model_dump(mode="json"),
        change,
        202,
        guard=guard,
    )


@router.get("/achievement-imports/{import_id}", response_model=ImportView)
def import_status(request: Request, actor: Actor, import_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        source = partner(request, session, actor)
        row = session.get(ImportJob, str(import_id))
        if row is None or row.source_id != source.source_id:
            raise HTTPException(404)
        return dict(import_id=row.import_id, status=row.status, results=row.results)


@router.get("/achievements/me", response_model=list[AchievementView])
def own_achievements(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        fence(request, session, actor.subject)
        query = select(AchievementRow).where(AchievementRow.candidate_id == str(actor.subject))
        if after:
            query = query.where(AchievementRow.achievement_id > str(after))
        return [
            achievement_view(row)
            for row in session.scalars(query.order_by(AchievementRow.achievement_id).limit(50))
        ]


@router.put("/achievements/{achievement_id}/visibility", response_model=AchievementView)
def visibility(
    request: Request,
    actor: Actor,
    achievement_id: UUID,
    body: Visibility,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")

    def guard(session):
        row = session.get(AchievementRow, str(achievement_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        fence(request, session, actor.subject)
        if body.published:
            connection_for(request, session, row.connection_id, actor.subject)
            consent(request, actor.subject, body.consent_id, "achievement_publication")

    def change(session):
        row = session.get(AchievementRow, str(achievement_id))
        if row.version != int(if_match.strip('"')) or (row.status == "revoked" and body.published):
            raise HTTPException(409)
        row.published, row.publication_consent_id, row.version = (
            body.published,
            str(body.consent_id) if body.consent_id else None,
            row.version + 1,
        )
        history(session, request, row, actor.subject, "visibility")
        return achievement_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_visibility:" + str(achievement_id),
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
        change,
        guard=guard,
        present=lambda session, _: achievement_view(
            session.get(AchievementRow, str(achievement_id))
        ),
    )


def reviewer_guard(request, session, actor, achievement_id):
    actor.require("achievement_moderator", mfa=True)
    row = session.get(AchievementRow, str(achievement_id))
    if row is None:
        raise HTTPException(404)
    for subject in sorted({str(actor.subject), row.candidate_id}):
        fence(request, session, subject)
    if row.candidate_id == str(actor.subject) or session.get(
        SourceRow, row.source_id
    ).partner_id == str(actor.subject):
        raise HTTPException(403)
    connection_for(request, session, row.connection_id, row.candidate_id)
    return row


@router.get("/achievements/{achievement_id}/review", response_model=AchievementView)
def review_evidence(request: Request, actor: Actor, achievement_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        return achievement_view(reviewer_guard(request, session, actor, achievement_id))


@router.post("/achievements/{achievement_id}/review", response_model=AchievementView)
def human_review(
    request: Request,
    actor: Actor,
    achievement_id: UUID,
    body: HumanReview,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("achievement_moderator", mfa=True)

    def guard(session):
        row = reviewer_guard(request, session, actor, achievement_id)
        if body.status == "confirmed" and row.data["revoked"]:
            raise HTTPException(409, "Source-revoked evidence cannot be confirmed")

    def change(session):
        row = session.get(AchievementRow, str(achievement_id))
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.status, row.version = body.status, row.version + 1
        history(session, request, row, actor.subject, "human_review", body.reason)
        return achievement_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_review:" + str(achievement_id),
        idempotency,
        {"body": body.model_dump(mode="json"), "version": if_match},
        change,
        guard=guard,
    )


@router.get("/achievements/{achievement_id}/history", response_model=list[HistoryView])
def own_history(request: Request, actor: Actor, achievement_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        fence(request, session, actor.subject)
        row = session.get(AchievementRow, str(achievement_id))
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        return [
            dict(
                version=item.version,
                action=item.action,
                reason=item.reason,
                snapshot=item.snapshot,
                at=utc(item.at).isoformat(),
            )
            for item in session.scalars(
                select(AchievementHistory)
                .where(AchievementHistory.achievement_id == str(achievement_id))
                .order_by(AchievementHistory.version)
                .limit(100)
            )
        ]


@internal_router.post("/{operation}", response_model=ExchangeReceipt)
def exchange(request: Request, body: ExchangeRequest, operation: str, signature: Signature = None):
    if operation != body.operation or operation not in {
        "connection",
        "import",
        "summary",
        "resume",
    }:
        raise HTTPException(422)

    def handle(session):
        if operation in {"summary", "resume"}:
            mode = body.payload.get("mode")
            if mode not in {"demo", "production"} or set(body.payload) != {"mode"}:
                raise HTTPException(422)
            fence(request, session, body.candidate_id)
            result = []
            seen_results = set()
            for row in session.scalars(
                select(AchievementRow)
                .where(
                    AchievementRow.candidate_id == str(body.candidate_id),
                    AchievementRow.published.is_(True),
                    AchievementRow.status == "confirmed",
                )
                .order_by(AchievementRow.achievement_id)
                .limit(50)
            ):  # noqa: E712
                if mode == "production" and row.demo:
                    continue
                try:
                    connection_for(request, session, row.connection_id, body.candidate_id)
                    consent(
                        request,
                        body.candidate_id,
                        row.publication_consent_id,
                        "achievement_publication",
                    )
                except HTTPException as exc:
                    if exc.status_code in {404, 409}:
                        continue
                    raise
                # One result mirrored by several sources contributes once.
                result_key = tuple(
                    " ".join(value.casefold().split()) if isinstance(value, str) else value
                    for value in (
                        row.data.get(key)
                        for key in (
                            "event",
                            "discipline",
                            "occurred_on",
                            "specialization",
                            "format",
                            "place",
                            "points",
                            "group_size",
                        )
                    )
                )
                if result_key in seen_results:
                    continue
                seen_results.add(result_key)
                result.append(
                    dict(
                        achievement_id=row.achievement_id,
                        version=row.version,
                        demo=row.demo,
                        source_id=row.source_id,
                        specialization=row.data["specialization"],
                        format=row.data["format"],
                        occurred_on=row.data["occurred_on"],
                    )
                )
                review = session.scalar(
                    select(AchievementHistory)
                    .where(
                        AchievementHistory.achievement_id == row.achievement_id,
                        AchievementHistory.version <= row.version,
                        AchievementHistory.action == "human_review",
                    )
                    .order_by(AchievementHistory.version.desc())
                )
                # A deleted independent reviewer is no longer a usable confirmation.
                if not row.demo and review is None:
                    result.pop()
                    seen_results.discard(result_key)
                    continue
                if review is not None:
                    try:
                        request.app.state.processing_access.check(UUID(review.actor_id))
                    except HTTPException as exc:
                        if exc.status_code in {403, 404, 409}:
                            result.pop()
                            seen_results.discard(result_key)
                            continue
                        raise
                if operation == "resume":
                    source = session.get(SourceRow, row.source_id)
                    result[-1].update(
                        source_name=source.name,
                        event=row.data["event"],
                        discipline=row.data["discipline"],
                        occurred_on=row.data["occurred_on"],
                        checked_at=utc(review.at) if review else utc(row.synced_at),
                        place=row.data.get("place"),
                        points=row.data.get("points"),
                    )
            return {"achievements": result}
        if set(body.payload) - {"connection_id", "records", "connection_version"}:
            raise HTTPException(422)
        row = connection_for(request, session, body.payload.get("connection_id"), body.candidate_id)
        source = session.get(SourceRow, row.source_id)
        if operation == "connection":
            return connection_view(row) | {
                "adapter": source.adapter,
                "demo": source.adapter.startswith("demo-"),
            }
        if not source.adapter.startswith("demo-"):
            raise HTTPException(403)
        if body.payload.get("connection_version") != row.version:
            raise HTTPException(409, "Connection changed during sync")
        records = [ImportedRecord.model_validate(item) for item in body.payload.get("records", [])]
        if len(records) > 100 or any(
            item.external_account != row.external_account for item in records
        ):
            raise HTTPException(422)
        result = apply_batch(request, session, source, records, body.candidate_id)
        row.last_synced_at, row.last_sync_status = (
            datetime.now(UTC),
            "ready" if not any(item["status"] == "error" for item in result) else "partial_failure",
        )
        return {"results": result, "status": row.last_sync_status}

    callers = (
        {"candidate"}
        if operation == "resume"
        else ({"matching"} if operation == "summary" else {"integration"})
    )
    return respond(request, body, signature, AchievementNonce, callers, handle)


def process_deletion_request(session, event):
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        candidate = str(event.payload["candidate_id"])
        state = lock(session, AchievementSubject, candidate, allow_blocked=True)
        if state.request_id and state.request_id != str(event.payload["request_id"]):
            raise HTTPException(409)
        first = state.request_id is None
        state.blocked, state.request_id = True, str(event.payload["request_id"])
        ids = list(
            session.scalars(
                select(AchievementRow.achievement_id).where(
                    AchievementRow.candidate_id == candidate
                )
            )
        )
        removed_jobs = []
        for job in session.scalars(select(ImportJob)):
            accounts = {
                row.external_account
                for row in session.scalars(
                    select(Connection).where(
                        Connection.candidate_id == candidate, Connection.source_id == job.source_id
                    )
                )
            }
            accounts |= {
                item.data["external_account"]
                for item in session.scalars(
                    select(AchievementRow).where(
                        AchievementRow.candidate_id == candidate,
                        AchievementRow.source_id == job.source_id,
                    )
                )
            }
            if job.created_by == candidate or any(
                item["external_account"] in accounts for item in job.records
            ):
                removed_jobs.append(job.import_id)
                session.delete(job)
        for source in session.scalars(select(SourceRow).where(SourceRow.partner_id == candidate)):
            source.partner_id, source.enabled, source.version = None, False, source.version + 1
        session.execute(delete(AchievementHistory).where(AchievementHistory.actor_id == candidate))
        for key in ids + removed_jobs:
            session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.response.contains(key))
            )
        session.execute(
            delete(IdempotencyRecord).where(IdempotencyRecord.response.contains(candidate))
        )
        for table in (AchievementHistory, AchievementRow, Connection):
            session.execute(delete(table).where(table.candidate_id == candidate))
        session.execute(
            delete(IdempotencyRecord).where(
                (IdempotencyRecord.actor_id == candidate)
                | IdempotencyRecord.operation.in_([f"achievement_review:{key}" for key in ids])
                | IdempotencyRecord.operation.in_([f"achievement_visibility:{key}" for key in ids])
            )
        )
        session.execute(
            delete(Outbox).where(
                Outbox.envelope["payload"]["candidate_id"].as_string() == candidate,
                Outbox.envelope["event_type"].as_string() != "achievements.data_deleted.v1",
            )
        )
        if first:
            enqueue(
                session,
                EventEnvelope(
                    producer="achievements",
                    event_type="achievements.data_deleted.v1",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    payload=event.payload,
                    aggregate_version=event.aggregate_version,
                ),
            )

    return consume_once(session, "achievements.deletion", event, apply)


def run_import(request):
    with Session(request.app.state.engine) as session:
        selected = session.scalar(
            select(ImportJob)
            .where(ImportJob.status == "pending")
            .order_by(ImportJob.import_id)
            .limit(1)
        )
        if selected is None:
            return False
        key, source_id, author, records = (
            selected.import_id,
            selected.source_id,
            selected.created_by,
            selected.records,
        )
    with Session(request.app.state.engine) as session, session.begin():
        accounts = {item["external_account"] for item in records}
        bindings = list(
            session.scalars(
                select(Connection).where(
                    Connection.source_id == source_id, Connection.external_account.in_(accounts)
                )
            )
        )
        for subject in sorted({author} | {row.candidate_id for row in bindings}):
            fence(request, session, subject)
        row = session.scalar(
            select(ImportJob)
            .where(ImportJob.import_id == key)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.status != "pending":
            return False
        source = session.get(SourceRow, row.source_id)
        try:
            allowed_source(request, source)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            row.status, row.results = "failed", [{"status": "source_disabled", "code": 409}]
            return True
        results = apply_batch(
            request,
            session,
            source,
            [ImportedRecord.model_validate(item) for item in row.records],
            UUID(row.created_by),
        )
        row.results, row.status = (
            results,
            "partial_failure"
            if any(item["status"] == "error" for item in results)
            else "completed",
        )
        return True


class RevokeCommand(Contract):
    external_version: int = Field(strict=True, ge=1)
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


@router.post("/achievements/{external_id}/revoke")
def partner_revoke(
    request: Request, actor: Actor, external_id: str, body: RevokeCommand, idempotency: CommandKey
):
    def guard(session):
        source = partner(request, session, actor)
        row = session.scalar(
            select(AchievementRow).where(
                AchievementRow.source_id == source.source_id,
                AchievementRow.external_id == external_id,
            )
        )
        if row is None:
            raise HTTPException(404)
        for subject in sorted({str(actor.subject), row.candidate_id}):
            fence(request, session, subject)

    def change(session):
        source = partner(request, session, actor)
        row = session.scalar(
            select(AchievementRow).where(
                AchievementRow.source_id == source.source_id,
                AchievementRow.external_id == external_id,
            )
        )
        if body.external_version < row.external_version:
            return {"status": "stale"}
        if body.external_version == row.external_version:
            if row.status != "revoked" or not row.data["revoked"]:
                raise HTTPException(409)
            return {"status": "duplicate"}
        row.status, row.external_version, row.version = (
            "revoked",
            body.external_version,
            row.version + 1,
        )
        row.data = row.data | {"external_version": body.external_version, "revoked": True}
        row.published, row.publication_consent_id = False, None
        history(session, request, row, actor.subject, "revoked", body.reason)
        return achievement_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_revoke:" + external_id,
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=guard,
    )


@router.post("/achievements/declared", response_model=AchievementView, status_code=201)
def declare(request: Request, actor: Actor, body: Declaration, idempotency: CommandKey):
    actor.require("candidate")

    def guard(session):
        fence(request, session, actor.subject)
        source = session.scalar(select(SourceRow).where(SourceRow.key == "self"))
        allowed_source(request, source)
        consent(request, actor.subject, body.consent_id, "achievement_import")

    def change(session):
        source = session.scalar(select(SourceRow).where(SourceRow.key == "self"))
        binding = session.scalar(
            select(Connection).where(
                Connection.source_id == source.source_id,
                Connection.candidate_id == str(actor.subject),
            )
        )
        if binding is None:
            binding = Connection(
                connection_id=str(uuid4()),
                candidate_id=str(actor.subject),
                source_id=source.source_id,
                external_account=str(actor.subject),
                consent_id=str(body.consent_id),
                status="active",
                version=1,
                expires_at=datetime.now(UTC),
            )
            session.add(binding)
        elif binding.status != "active":
            raise HTTPException(409, "Reconnect before declaring another achievement")
        elif binding.consent_id != str(body.consent_id):
            binding.consent_id, binding.version = str(body.consent_id), binding.version + 1
        record = ImportedRecord(
            **body.model_dump(exclude={"consent_id"}),
            external_id=str(uuid4()),
            external_account=str(actor.subject),
            external_version=1,
        )
        row = AchievementRow(
            achievement_id=str(uuid4()),
            source_id=source.source_id,
            external_id=record.external_id,
            connection_id=binding.connection_id,
            candidate_id=str(actor.subject),
            data=record.model_dump(mode="json"),
            external_version=1,
            version=1,
            status="declared",
            demo=request.app.state.settings.deployment_mode == "demo",
            published=False,
            publication_consent_id=None,
            synced_at=datetime.now(UTC),
        )
        session.add(row)
        history(session, request, row, actor.subject, "declared")
        return {"achievement_id": row.achievement_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "achievement_declare",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, result: achievement_view(
            session.get(AchievementRow, result["achievement_id"])
        ),
    )
