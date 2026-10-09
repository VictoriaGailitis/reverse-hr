"""Subject rights requests and immediate, reversible processing restrictions."""

from datetime import UTC, datetime, timedelta
from typing import Literal, get_args
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, String, delete, or_, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.domains.privacy import PrivacyBase, subject_lock, utc
from reverse_hr.settings import SERVICES

ACCESS_SCOPES = set(SERVICES) | {None}


class SubjectRequest(PrivacyBase):
    __tablename__ = "privacy_subject_requests"
    request_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    domain: Mapped[str | None] = mapped_column(String(50))
    purpose: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(16))
    assignee_id: Mapped[str | None] = mapped_column(String(36))
    data: Mapped[dict] = mapped_column(JSON)
    restriction_active: Mapped[bool]
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    due_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class RequestHistory(PrivacyBase):
    __tablename__ = "privacy_request_history"
    history_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    version: Mapped[int]
    action: Mapped[str] = mapped_column(String(32))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    details: Mapped[dict] = mapped_column(JSON)


class RequestCommand(Contract):
    kind: Literal["access", "correction", "restriction"]
    domain: str | None = Field(default=None, max_length=50)
    purpose: str | None = Field(default=None, max_length=50)
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")
    proposed_changes: dict = Field(default_factory=dict)
    source_version: int | None = Field(default=None, strict=True, ge=0)
    target: Literal[
        "profile",
        "contacts",
        "resume",
        "preferences",
        "declared_achievement",
        "notification_preferences",
    ] = "profile"
    target_id: UUID | None = None
    source_profile_version: int | None = Field(default=None, strict=True, ge=1)

    @model_validator(mode="after")
    def supported(self):
        from reverse_hr.domains.privacy import POLICIES

        if self.domain is not None and self.domain not in SERVICES:
            raise ValueError("Unknown domain")
        if self.purpose is not None and self.purpose not in POLICIES:
            raise ValueError("Unknown purpose")
        if self.kind == "restriction" and self.domain is not None:
            from reverse_hr.processing_access import ProcessingRequest

            if self.domain not in get_args(ProcessingRequest.model_fields["requester"].annotation):
                raise ValueError("This domain has no processing permission enforcement")
        if self.kind == "correction":
            if (
                self.domain not in {"candidate", "achievements", "notification"}
                or self.purpose is not None
                or self.source_version is None
            ):
                raise ValueError("Only versioned candidate self-description corrections supported")
            from reverse_hr.rights_corrections import validate

            validate(
                self.target,
                self.domain,
                self.proposed_changes,
                self.source_profile_version,
                self.target_id,
            )
            if self.target != "preferences" and self.source_version == 0:
                raise ValueError("Existing source version required")
        elif (
            self.proposed_changes
            or self.source_version is not None
            or self.source_profile_version is not None
            or self.target != "profile"
            or self.target_id is not None
        ):
            raise ValueError("Only correction requests contain proposed changes")
        if self.kind == "access" and self.purpose is not None:
            raise ValueError("Access is domain scoped")
        return self


class RequestView(Contract):
    request_id: UUID
    candidate_id: UUID
    kind: Literal["access", "correction", "restriction"]
    domain: str | None
    purpose: str | None
    status: Literal[
        "submitted", "in_review", "approved", "applying", "rejected", "completed", "withdrawn"
    ]
    assignee_id: UUID | None
    data: dict
    restriction_active: bool
    version: int
    created_at: datetime
    due_at: datetime
    completed_at: datetime | None


class Decision(Contract):
    outcome: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


router = APIRouter(prefix="/v1/data-subject-requests", tags=["privacy-rights"])


def view(row):
    values = {key: getattr(row, key) for key in RequestView.model_fields}
    for field in ("created_at", "due_at", "completed_at"):
        if values[field] is not None:
            values[field] = utc(values[field])
    return RequestView(**values).model_dump(mode="json")


def audit(session, row, actor, action, **details):
    from reverse_hr.db import enqueue
    from reverse_hr.events import EventEnvelope

    enqueue(
        session,
        EventEnvelope(
            producer="privacy",
            event_type="privacy.archive_completed.v1"
            if action == "archive_completed"
            else "privacy.subject_request_changed.v1",
            aggregate_id=UUID(row.request_id),
            aggregate_version=row.version,
            correlation_id=uuid4(),
            payload={
                "candidate_id": UUID(row.candidate_id),
                "actor_id": UUID(str(actor)),
                "request_id": UUID(row.request_id),
            },
        ),
    )
    session.add(
        RequestHistory(
            history_id=str(uuid4()),
            request_id=row.request_id,
            candidate_id=row.candidate_id,
            actor_id=str(actor),
            version=row.version,
            action=action,
            at=datetime.now(UTC),
            details=details,
        )
    )


def restriction(session, candidate, *, domain=None, purpose=None):
    rows = session.scalars(
        select(SubjectRequest).where(
            SubjectRequest.candidate_id == str(candidate),
            SubjectRequest.restriction_active.is_(True),
        )
    )
    return any(
        (row.domain is None or row.domain == domain)
        and (row.purpose is None or row.purpose == purpose)
        for row in rows
    )


def guard(request, session, actor, request_id=None, *, officer=False):
    row = session.get(SubjectRequest, str(request_id)) if request_id else None
    if request_id and row is None:
        raise HTTPException(404)
    if officer:
        actor.require("privacy_officer", mfa=True)
        if row.candidate_id == str(actor.subject):
            raise HTTPException(403, "Independent reviewer required")
    elif row and row.candidate_id != str(actor.subject):
        raise HTTPException(404)
    else:
        # Actor is an authenticated, verified account; its own rights are not
        # conditional on using the candidate product role.
        pass
    subjects = {str(actor.subject)} | ({row.candidate_id} if row else set())
    for candidate in sorted(subjects):
        subject_lock(session, candidate)
    if row:
        row = session.scalar(
            select(SubjectRequest)
            .where(SubjectRequest.request_id == str(request_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    return row


@router.post("", response_model=RequestView, status_code=201)
def submit(request: Request, actor: Actor, body: RequestCommand, idempotency: CommandKey):
    if body.kind == "access" and body.domain not in ACCESS_SCOPES:
        raise HTTPException(409, "Choose a supported explicit access domain")

    def change(session):
        pending = session.scalar(
            select(SubjectRequest.request_id).where(
                SubjectRequest.candidate_id == str(actor.subject),
                SubjectRequest.kind == body.kind,
                SubjectRequest.domain == body.domain,
                SubjectRequest.purpose == body.purpose,
                or_(
                    SubjectRequest.status.in_(["submitted", "in_review", "approved", "applying"]),
                    SubjectRequest.restriction_active.is_(True),
                ),
            )
        )
        if pending:
            raise HTTPException(409, "An active request for this scope exists")
        now = datetime.now(UTC)
        row = SubjectRequest(
            request_id=str(uuid4()),
            candidate_id=str(actor.subject),
            kind=body.kind,
            domain=body.domain,
            purpose=body.purpose,
            status="submitted",
            assignee_id=None,
            data=body.model_dump(mode="json"),
            restriction_active=body.kind == "restriction",
            version=1,
            created_at=now,
            due_at=now + timedelta(days=request.app.state.settings.privacy_request_sla_days),
            completed_at=None,
        )
        session.add(row)
        audit(session, row, actor.subject, "submitted")
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "subject_request",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: guard(request, session, actor),
        present=lambda session, value: view(session.get(SubjectRequest, value["request_id"])),
    )


@router.get("", response_model=list[RequestView])
def own_requests(request: Request, actor: Actor, after: UUID | None = None):
    with Session(request.app.state.engine) as session, session.begin():
        guard(request, session, actor)
        query = select(SubjectRequest).where(SubjectRequest.candidate_id == str(actor.subject))
        if after:
            query = query.where(SubjectRequest.request_id > str(after))
        return [
            view(row)
            for row in session.scalars(query.order_by(SubjectRequest.request_id).limit(100))
        ]


@router.get("/queue", response_model=list[RequestView])
def queue(request: Request, actor: Actor):
    actor.require("privacy_officer", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        query = (
            select(SubjectRequest)
            .where(
                SubjectRequest.candidate_id != str(actor.subject),
                SubjectRequest.status.in_(["submitted", "in_review", "approved", "applying"]),
            )
            .order_by(SubjectRequest.due_at)
            .limit(100)
        )
        pending = list(session.scalars(query))
        subjects = {str(actor.subject)} | {row.candidate_id for row in pending}
        states = {
            subject: subject_lock(session, subject, allow_blocked=True)
            for subject in sorted(subjects)
        }
        if states[str(actor.subject)].blocked:
            raise HTTPException(409)
        return [view(row) for row in pending if not states[row.candidate_id].blocked]


def read_guard(request, session, actor, request_id):
    row = session.get(SubjectRequest, str(request_id))
    officer = bool(
        row and row.candidate_id != str(actor.subject) and "privacy_officer" in actor.roles
    )
    return guard(request, session, actor, request_id, officer=officer)


@router.get("/{request_id}", response_model=RequestView)
def read(request: Request, actor: Actor, request_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        return view(read_guard(request, session, actor, request_id))


@router.post("/{request_id}/claim", response_model=RequestView)
def claim(
    request: Request,
    actor: Actor,
    request_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(SubjectRequest, str(request_id))
        recover = row.assignee_id is None and row.status in {"in_review", "approved", "applying"}
        if (row.status != "submitted" and not recover) or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.status = row.status if recover else "in_review"
        row.assignee_id, row.version = str(actor.subject), row.version + 1
        audit(session, row, actor.subject, "claimed")
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "subject_claim:" + str(request_id),
        idempotency,
        dict(version=if_match),
        change,
        guard=lambda session: guard(request, session, actor, request_id, officer=True),
        present=lambda session, _: view(session.get(SubjectRequest, str(request_id))),
    )


@router.post("/{request_id}/decision", response_model=RequestView)
def decide(
    request: Request,
    actor: Actor,
    request_id: UUID,
    body: Decision,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(SubjectRequest, str(request_id))
        if (
            row.status != "in_review"
            or row.assignee_id != str(actor.subject)
            or row.version != int(if_match.strip('"'))
        ):
            raise HTTPException(409)
        row.status, row.version = body.outcome, row.version + 1
        row.data = row.data | {"decision": body.model_dump(mode="json")}
        if body.outcome == "rejected":
            row.restriction_active = False
        elif row.kind == "restriction":
            row.status, row.completed_at = "completed", datetime.now(UTC)
        audit(session, row, actor.subject, "decided", **body.model_dump(mode="json"))
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "subject_decide:" + str(request_id),
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        guard=lambda session: guard(request, session, actor, request_id, officer=True),
        present=lambda session, _: view(session.get(SubjectRequest, str(request_id))),
    )


@router.post("/{request_id}/withdraw", response_model=RequestView)
def withdraw(
    request: Request,
    actor: Actor,
    request_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(SubjectRequest, str(request_id))
        if row.status == "applying":
            raise HTTPException(409, "Approved correction is being applied")
        if row.version != int(if_match.strip('"')) or (
            row.status in {"withdrawn", "rejected", "completed"}
            and not row.restriction_active
            and row.kind != "access"
        ):
            raise HTTPException(409)
        row.status, row.restriction_active, row.version = "withdrawn", False, row.version + 1
        from reverse_hr.domains.privacy_archives import scrub as scrub_archives

        scrub_archives(session, request_id=request_id)
        audit(session, row, actor.subject, "withdrawn")
        return view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "subject_withdraw:" + str(request_id),
        idempotency,
        dict(version=if_match),
        change,
        guard=lambda session: guard(request, session, actor, request_id),
        present=lambda session, _: view(session.get(SubjectRequest, str(request_id))),
    )


@router.get("/{request_id}/history")
def history(
    request: Request, actor: Actor, request_id: UUID, after_version: int = Query(default=0, ge=0)
):
    with Session(request.app.state.engine) as session, session.begin():
        read_guard(request, session, actor, request_id)
        return [
            dict(
                version=row.version,
                action=row.action,
                at=utc(row.at).isoformat(),
                details=row.details,
            )
            for row in session.scalars(
                select(RequestHistory)
                .where(
                    RequestHistory.request_id == str(request_id),
                    RequestHistory.version > after_version,
                )
                .order_by(RequestHistory.version)
                .limit(100)
            )
        ]


def scrub(session, subject):
    from reverse_hr.db import Outbox

    event_types = ["privacy.subject_request_changed.v1", "privacy.archive_completed.v1"]
    session.execute(
        delete(Outbox).where(
            Outbox.envelope["event_type"].as_string().in_(event_types),
            Outbox.envelope["payload"]["candidate_id"].as_string() == str(subject),
        )
    )
    for event in session.scalars(
        select(Outbox).where(
            Outbox.envelope["event_type"].as_string().in_(event_types),
            Outbox.envelope["payload"]["actor_id"].as_string() == str(subject),
        )
    ):
        payload = {k: v for k, v in event.envelope["payload"].items() if k != "actor_id"}
        event.envelope = event.envelope | {"payload": payload}
    from reverse_hr.domains.privacy_archives import scrub as scrub_archives

    scrub_archives(session, subject=subject)
    from reverse_hr.db import IdempotencyRecord

    identifiers = list(
        session.scalars(
            select(SubjectRequest.request_id).where(SubjectRequest.candidate_id == str(subject))
        )
    )
    references = [IdempotencyRecord.response.contains(str(subject))]
    references += [IdempotencyRecord.response.contains(key) for key in identifiers]
    session.execute(
        delete(IdempotencyRecord).where(
            IdempotencyRecord.operation != "request_deletion",
            or_(IdempotencyRecord.actor_id == str(subject), *references),
        )
    )
    session.execute(
        delete(RequestHistory).where(
            (RequestHistory.candidate_id == str(subject))
            | (RequestHistory.actor_id == str(subject))
        )
    )
    session.execute(delete(SubjectRequest).where(SubjectRequest.candidate_id == str(subject)))
    # Deleting a responsible officer releases work rather than retaining their identity.
    for row in session.scalars(
        select(SubjectRequest).where(SubjectRequest.assignee_id == str(subject))
    ):
        row.assignee_id, row.version = None, row.version + 1


@router.get("/{request_id}/export")
def export(request: Request, actor: Actor, request_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = guard(request, session, actor, request_id)
        if row.kind != "access" or row.status not in {"approved", "completed"}:
            raise HTTPException(409)
        domain, revision = row.domain, row.version
        if domain not in {"privacy", "candidate", "achievements", "hiring"}:
            raise HTTPException(409, "Use paginated archives for this scope")
        if domain == "privacy":
            from reverse_hr.privacy_request_exchange import snapshot

            data = snapshot(session, "privacy", actor.subject)
        else:
            data = None
    if data is None:
        data = request.app.state.rights_access.call(
            domain, "export", actor.subject, request_id, revision
        )
    import json

    from reverse_hr.privacy_request_exchange import LIMIT

    if len(json.dumps(data, ensure_ascii=False).encode("utf-8")) > LIMIT:
        raise HTTPException(409, "Archive exceeds supported response size")
    with Session(request.app.state.engine) as session, session.begin():
        row = guard(request, session, actor, request_id)
        if row.version != revision or row.status not in {"approved", "completed"}:
            raise HTTPException(409, "Request authorization changed during export")
        return JSONResponse(
            dict(
                request_id=str(request_id),
                scope=domain,
                complete=False,
                coverage="legacy_projection",
                data=data,
            ),
            headers={
                "Cache-Control": "no-store",
                "Content-Disposition": 'attachment; filename="subject-data.json"',
            },
        )


@router.post("/{request_id}/execute", response_model=RequestView)
def apply_correction(
    request: Request,
    actor: Actor,
    request_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    # Reserve the approved action before remote I/O. Once applying, withdrawal is refused.
    # This gives retries one stable owner command while avoiding a reverse RPC lock cycle.
    with Session(request.app.state.engine) as session, session.begin():
        row = guard(request, session, actor, request_id, officer=True)
        if row.kind != "correction" or row.assignee_id != str(actor.subject):
            raise HTTPException(409)
        execution = row.data.get("execution")
        if execution:
            if execution != {"key": idempotency, "expected_version": if_match}:
                raise HTTPException(409)
            if row.status == "completed":
                return view(row)
            if row.status != "applying":
                raise HTTPException(409)
        else:
            if row.status != "approved" or row.version != int(if_match.strip('"')):
                raise HTTPException(409)
            row.status, row.version = "applying", row.version + 1
            row.data = row.data | {"execution": {"key": idempotency, "expected_version": if_match}}
            audit(session, row, actor.subject, "applying")
        candidate, revision, owner = UUID(row.candidate_id), row.version, row.domain
        expected_target = row.data.get("target", "profile")
        source_version = row.data["source_version"]
        source_profile_version = row.data.get("source_profile_version")
    try:
        result = request.app.state.rights_access.call(
            owner, "correct", candidate, request_id, revision
        )
    except HTTPException as exc:
        if exc.status_code == 409:
            with Session(request.app.state.engine) as session, session.begin():
                row = guard(request, session, actor, request_id, officer=True)
                if row.status == "applying" and row.version == revision:
                    row.status, row.version = "in_review", row.version + 1
                    row.data = {key: value for key, value in row.data.items() if key != "execution"}
                    audit(session, row, actor.subject, "source_conflict")
        raise
    if set(result) not in (
        {"candidate_id", "profile_version"},
        {"candidate_id", "target", "version"},
        {"candidate_id", "target", "version", "profile_version"},
    ) or result.get("candidate_id") != str(candidate):
        raise HTTPException(503)
    if expected_target == "profile":
        if (
            type(result.get("profile_version")) is not int
            or result["profile_version"] != source_version + 1
        ):
            raise HTTPException(503, "Unbound correction receipt")
    else:
        if (
            result.get("target") != expected_target
            or type(result.get("version")) is not int
            or result["version"] != source_version + 1
        ):
            raise HTTPException(503, "Unbound correction receipt")
        if expected_target in {"resume", "preferences"} and (
            type(result.get("profile_version")) is not int
            or result["profile_version"] != source_profile_version + 1
        ):
            raise HTTPException(503, "Unbound profile correction receipt")
    with Session(request.app.state.engine) as session, session.begin():
        row = guard(request, session, actor, request_id, officer=True)
        if row.status == "completed" and row.data.get("result") == result:
            return view(row)
        if row.status != "applying" or row.version != revision:
            raise HTTPException(409)
        row.status, row.version, row.completed_at = "completed", row.version + 1, datetime.now(UTC)
        row.data = row.data | {"result": result}
        audit(session, row, actor.subject, "applied", **result)
        return view(row)
