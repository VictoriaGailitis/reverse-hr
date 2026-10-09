"""Company-owned needs and invitation transitions; contact grants remain in Privacy."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import JSON, DateTime, String, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import ContactView, Contract
from reverse_hr.db import enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.market_access import Signature, respond
from reverse_hr.market_contracts import (
    Acceptance,
    CandidateCard,
    InvitationCreate,
    InvitationView,
    MarketReceipt,
    MarketRequest,
    NeedCommand,
    NeedView,
)
from reverse_hr.market_state import NonceColumns, SubjectColumns, lock


class HiringBase(DeclarativeBase):
    pass


class HiringSubject(SubjectColumns, HiringBase):
    __tablename__ = "hiring_subjects"


class HiringNonce(NonceColumns, HiringBase):
    __tablename__ = "hiring_market_nonces"


class Need(HiringBase):
    __tablename__ = "hiring_needs"
    need_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    spec: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int]


class InvitationRow(HiringBase):
    __tablename__ = "hiring_invitations"
    invitation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consent_id: Mapped[str | None] = mapped_column(String(36))


class InvitationRevision(HiringBase):
    __tablename__ = "hiring_invitation_revisions"
    invitation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    predecessor_id: Mapped[str | None] = mapped_column(String(36))
    terms: Mapped[dict] = mapped_column(JSON)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class RevisionView(Contract):
    invitation_id: UUID
    version: int
    predecessor_id: UUID | None
    terms: InvitationCreate
    recorded_at: datetime


def record_terms(session, row, predecessor=None):
    session.add(
        InvitationRevision(
            invitation_id=row.invitation_id,
            version=row.version,
            candidate_id=row.candidate_id,
            created_by=row.created_by,
            predecessor_id=predecessor,
            terms=dict(row.spec),
            recorded_at=datetime.now(UTC),
        )
    )


router = APIRouter(prefix="/v1", tags=["hiring"])
internal_router = APIRouter(prefix="/internal/v1/market", tags=["internal-hiring"])


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def member(request, actor, organization):
    actor.require("employer")
    return request.app.state.market_access.require(
        "employer",
        "membership",
        candidate_id=actor.subject,
        actor_id=actor.subject,
        organization_id=organization,
    )


def need_view(row):
    return NeedView(
        **row.spec, need_id=row.need_id, created_by=row.created_by, version=row.version
    ).model_dump(mode="json")


def invitation_view(row):
    data = {k: v for k, v in row.spec.items() if k != "expires_in_days"}
    status = (
        "expired"
        if row.status in {"sent", "viewed"} and utc(row.expires_at) <= datetime.now(UTC)
        else row.status
    )
    return InvitationView(
        **data,
        invitation_id=row.invitation_id,
        status=status,
        version=row.version,
        expires_at=utc(row.expires_at),
    ).model_dump(mode="json")


def emit(session, request, aggregate, version, kind, refs):
    enqueue(
        session,
        EventEnvelope(
            producer="hiring",
            event_type=f"hiring.{kind}.v1",
            correlation_id=request.state.trace_id,
            aggregate_id=UUID(str(aggregate)),
            aggregate_version=version,
            payload=refs,
        ),
    )


@router.post("/hiring-needs", response_model=NeedView, status_code=201)
def create_need(request: Request, actor: Actor, body: NeedCommand, idempotency: CommandKey):
    member(request, actor, body.organization_id)

    def guard(session):
        lock(session, HiringSubject, actor.subject)
        member(request, actor, body.organization_id)

    def change(session):
        row = Need(
            need_id=str(uuid4()),
            organization_id=str(body.organization_id),
            created_by=str(actor.subject),
            spec=body.model_dump(mode="json"),
            version=1,
        )
        session.add(row)
        emit(
            session,
            request,
            row.need_id,
            1,
            "need_changed",
            dict(
                need_id=UUID(row.need_id),
                organization_id=body.organization_id,
                actor_id=actor.subject,
            ),
        )
        return need_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_need",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
    )


@router.put("/hiring-needs/{need_id}", response_model=NeedView)
def update_need(
    request: Request,
    actor: Actor,
    need_id: UUID,
    body: NeedCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    member(request, actor, body.organization_id)

    def guard(session):
        existing = session.get(Need, str(need_id))
        if existing is None or existing.organization_id != str(body.organization_id):
            raise HTTPException(404)
        from reverse_hr.domains.hiring_vacancies import Vacancy

        if session.scalar(select(Vacancy.vacancy_id).where(Vacancy.need_id == str(need_id))):
            raise HTTPException(409, "Managed vacancy requirements use the vacancy API")
        for subject in sorted({str(actor.subject), existing.created_by}):
            lock(session, HiringSubject, subject)
        request.app.state.processing_access.check(UUID(existing.created_by))
        member(request, actor, body.organization_id)

    def change(session):
        row = session.scalar(
            select(Need)
            .where(Need.need_id == str(need_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None or row.organization_id != str(body.organization_id):
            raise HTTPException(404)
        request.app.state.processing_access.check(UUID(row.created_by))
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.spec, row.version = body.model_dump(mode="json"), row.version + 1
        emit(
            session,
            request,
            need_id,
            row.version,
            "need_changed",
            dict(need_id=need_id, organization_id=body.organization_id, actor_id=actor.subject),
        )
        return need_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"update_need:{need_id}",
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        guard=guard,
    )


@internal_router.post("/need", response_model=MarketReceipt)
def export_need(request: Request, body: MarketRequest, signature: Signature = None):
    def check(session):
        row = session.get(Need, str(body.need_id))
        owners = {str(body.actor_id)} | ({row.created_by} if row else set())
        from reverse_hr.domains.hiring_vacancies import Vacancy, VacancyDecision, owner_active

        vacancy = session.scalar(select(Vacancy).where(Vacancy.need_id == str(body.need_id)))
        decision = (
            session.scalar(
                select(VacancyDecision).where(
                    VacancyDecision.vacancy_id == vacancy.vacancy_id,
                    VacancyDecision.revision == vacancy.revision,
                )
            )
            if vacancy
            else None
        )
        owners |= {decision.reviewer_id} if decision else set()
        states = [
            lock(session, HiringSubject, subject, allow_blocked=True) for subject in sorted(owners)
        ]
        row = session.scalar(
            select(Need)
            .where(Need.need_id == str(body.need_id))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            any(state.blocked for state in states)
            or row is None
            or row.organization_id != str(body.organization_id)
            or row.spec["status"] != "published"
        ):
            return None, row.version if row else 0
        try:
            request.app.state.processing_access.check(UUID(row.created_by))
            if vacancy:
                session.refresh(vacancy)
                current = session.scalar(
                    select(VacancyDecision).where(
                        VacancyDecision.vacancy_id == vacancy.vacancy_id,
                        VacancyDecision.revision == vacancy.revision,
                    )
                )
                if (
                    vacancy.status != "published"
                    or not current
                    or current.outcome != "approved"
                    or current.reviewer_id not in owners
                ):
                    return None, row.version
                request.app.state.processing_access.check(UUID(current.reviewer_id))
                owner_active(request, vacancy)
            request.app.state.market_access.require(
                "employer",
                "membership",
                candidate_id=body.actor_id,
                actor_id=body.actor_id,
                organization_id=body.organization_id,
            )
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            return None, row.version
        return need_view(row), row.version

    return respond(request, body, signature, "hiring", "need", HiringNonce, {"matching"}, check)


@router.post("/invitations", response_model=InvitationView, status_code=201)
def invite(request: Request, actor: Actor, body: InvitationCreate, idempotency: CommandKey):
    member(request, actor, body.organization_id)

    def guard(session):
        for subject in sorted({str(actor.subject), str(body.candidate_id)}):
            lock(session, HiringSubject, subject)
        member(request, actor, body.organization_id)
        from reverse_hr.domains.hiring_dialogs import blocked

        if blocked(session, body.candidate_id, body.organization_id):
            raise HTTPException(409)
        request.app.state.processing_access.check(body.candidate_id)
        receipt = request.app.state.market_access.require(
            "candidate", "profile", candidate_id=body.candidate_id
        )
        card = CandidateCard.model_validate(receipt.data)
        if card.candidate_id != body.candidate_id:
            raise HTTPException(409)

    def change(session):
        return invitation_view(create_invitation(session, request, actor, body))

    return execute(
        request.app.state.engine,
        actor.subject,
        "invite",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, value: invitation_view(
            session.get(InvitationRow, value["invitation_id"])
        ),
    )


def create_invitation(session, request, actor, body, *, draft=False, predecessor=None):
    row = InvitationRow(
        invitation_id=str(uuid4()),
        candidate_id=str(body.candidate_id),
        organization_id=str(body.organization_id),
        created_by=str(actor.subject),
        spec=body.model_dump(mode="json"),
        status="draft" if draft else "sent",
        version=1,
        expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days),
    )
    session.add(row)
    record_terms(session, row, predecessor)
    if draft:
        return row
    emit(
        session,
        request,
        row.invitation_id,
        1,
        "invitation_sent",
        dict(
            invitation_id=UUID(row.invitation_id),
            organization_id=body.organization_id,
            candidate_id=body.candidate_id,
        ),
    )
    from reverse_hr.domains.hiring_dialogs import notify

    notify(session, request, row, row.candidate_id, "invitation_sent", actor.subject)
    return row


def invitation_guard(request, actor, invitation_id, session, candidate_only=False, subjects=()):
    row = session.get(InvitationRow, str(invitation_id))
    if row is None:
        raise HTTPException(404)
    from reverse_hr.domains.hiring_vacancies import Application

    application = session.scalar(
        select(Application).where(Application.invitation_id == str(invitation_id))
    )
    subjects = set(subjects) | ({application.created_by} if application else set())
    for subject in sorted({str(actor.subject), row.candidate_id, row.created_by} | set(subjects)):
        lock(session, HiringSubject, subject)
    row = session.scalar(
        select(InvitationRow)
        .where(InvitationRow.invitation_id == str(invitation_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        raise HTTPException(404)
    request.app.state.processing_access.check(UUID(row.candidate_id))
    request.app.state.processing_access.check(UUID(row.created_by))
    for subject in sorted(subjects):
        request.app.state.processing_access.check(UUID(str(subject)))
    if row.candidate_id == str(actor.subject):
        actor.require("candidate")
        if row.status == "draft":
            raise HTTPException(404)
    elif candidate_only:
        raise HTTPException(404)
    else:
        member(request, actor, UUID(row.organization_id))
    return row


@router.get("/invitations", response_model=list[InvitationView])
def list_invitations(
    request: Request, actor: Actor, organization_id: UUID | None = None, after: UUID | None = None
):
    if organization_id:
        member(request, actor, organization_id)
    else:
        actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        query = (
            select(InvitationRow).where(InvitationRow.organization_id == str(organization_id))
            if organization_id
            else select(InvitationRow).where(InvitationRow.candidate_id == str(actor.subject))
        )
        if after:
            query = query.where(InvitationRow.invitation_id > str(after))
        rows = list(session.scalars(query.order_by(InvitationRow.invitation_id).limit(50)))
        subjects = (
            {str(actor.subject)}
            | {row.candidate_id for row in rows}
            | {row.created_by for row in rows}
        )
        states = {
            subject: lock(session, HiringSubject, subject, allow_blocked=True)
            for subject in sorted(subjects)
        }
        if states[str(actor.subject)].blocked:
            raise HTTPException(409)
        result = []
        for row in rows:
            if (
                (not organization_id and row.status == "draft")
                or states[row.candidate_id].blocked
                or states[row.created_by].blocked
            ):
                continue
            try:
                request.app.state.processing_access.check(UUID(row.candidate_id))
                request.app.state.processing_access.check(UUID(row.created_by))
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                continue
            result.append(invitation_view(row))
        return result


@router.get("/hiring-needs", response_model=list[NeedView])
def list_needs(request: Request, actor: Actor, organization_id: UUID, after: UUID | None = None):
    member(request, actor, organization_id)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(Need).where(Need.organization_id == str(organization_id))
        if after:
            query = query.where(Need.need_id > str(after))
        rows = list(session.scalars(query.order_by(Need.need_id).limit(50)))
        states = {
            subject: lock(session, HiringSubject, subject, allow_blocked=True)
            for subject in sorted({str(actor.subject)} | {row.created_by for row in rows})
        }
        if states[str(actor.subject)].blocked:
            raise HTTPException(409)
        result = []
        for row in rows:
            if states[row.created_by].blocked:
                continue
            try:
                request.app.state.processing_access.check(UUID(row.created_by))
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                continue
            result.append(need_view(row))
        return result


@router.get("/invitations/{invitation_id}", response_model=InvitationView)
def get_invitation(request: Request, actor: Actor, invitation_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        return invitation_view(invitation_guard(request, actor, invitation_id, session))


@router.post("/invitations/{invitation_id}/accept", response_model=InvitationView)
def accept(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    body: Acceptance,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        row = invitation_guard(request, actor, invitation_id, session, True)
        from reverse_hr.domains.hiring_dialogs import blocked

        if blocked(session, row.candidate_id, row.organization_id):
            raise HTTPException(409)
        request.app.state.market_access.require(
            "privacy",
            "purpose-permission",
            candidate_id=actor.subject,
            consent_id=body.disclosure_consent_id,
            consent_purpose="contact_disclosure",
        )
        return row

    def change(session):
        row = session.get(InvitationRow, str(invitation_id))
        if (
            row.status not in {"sent", "viewed"}
            or utc(row.expires_at) <= datetime.now(UTC)
            or row.version != int(if_match.strip('"'))
        ):
            raise HTTPException(409)
        row.status, row.version, row.consent_id = (
            "accepted",
            row.version + 1,
            str(body.disclosure_consent_id),
        )
        emit(
            session,
            request,
            invitation_id,
            row.version,
            "invitation_accepted",
            dict(
                invitation_id=invitation_id,
                candidate_id=actor.subject,
                organization_id=UUID(row.organization_id),
                consent_id=body.disclosure_consent_id,
            ),
        )
        from reverse_hr.domains.hiring_dialogs import notify, open_dialog

        open_dialog(session, row)
        notify(session, request, row, row.created_by, "invitation_accepted", actor.subject)
        return invitation_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"accept:{invitation_id}",
        idempotency,
        dict(consent=str(body.disclosure_consent_id), version=if_match),
        change,
        guard=guard,
        present=lambda session, _: invitation_view(session.get(InvitationRow, str(invitation_id))),
    )


def transition(request, actor, invitation_id, idempotency, if_match, status):
    def guard(session):
        row = invitation_guard(request, actor, invitation_id, session, status == "declined")
        if status == "revoked":
            member(request, actor, UUID(row.organization_id))

    def change(session):
        row = session.get(InvitationRow, str(invitation_id))
        if (
            row.status not in {"sent", "viewed"}
            or utc(row.expires_at) <= datetime.now(UTC)
            or row.version != int(if_match.strip('"'))
        ):
            raise HTTPException(409)
        row.status, row.version = status, row.version + 1
        from reverse_hr.domains.hiring_vacancies import invitation_closed

        invitation_closed(session, request, actor, row)
        emit(
            session,
            request,
            invitation_id,
            row.version,
            "invitation_" + status,
            dict(
                invitation_id=invitation_id,
                candidate_id=UUID(row.candidate_id),
                organization_id=UUID(row.organization_id),
            ),
        )
        from reverse_hr.domains.hiring_dialogs import notify

        notify(
            session,
            request,
            row,
            row.created_by if status == "declined" else row.candidate_id,
            "invitation_" + status,
            actor.subject,
        )
        return invitation_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"{status}:{invitation_id}",
        idempotency,
        dict(version=if_match),
        change,
        guard=guard,
        present=lambda session, _: invitation_view(session.get(InvitationRow, str(invitation_id))),
    )


@router.post("/invitations/{invitation_id}/decline", response_model=InvitationView)
def decline(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return transition(request, actor, invitation_id, idempotency, if_match, "declined")


@router.post("/invitations/{invitation_id}/revoke", response_model=InvitationView)
def revoke(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return transition(request, actor, invitation_id, idempotency, if_match, "revoked")


@router.get("/invitations/{invitation_id}/contacts", response_model=ContactView)
def contacts(request: Request, actor: Actor, invitation_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = invitation_guard(request, actor, invitation_id, session)
        member(request, actor, UUID(row.organization_id))
        from reverse_hr.domains.hiring_dialogs import blocked

        if row.status != "accepted" or blocked(session, row.candidate_id, row.organization_id):
            raise HTTPException(409)
        refs = dict(
            candidate_id=UUID(row.candidate_id),
            actor_id=actor.subject,
            organization_id=UUID(row.organization_id),
            invitation_id=invitation_id,
        )
        # Keep the local subject fence until disclosure; block/deletion cannot overtake it.
        # Sensitive contacts are neither indexed nor persisted in Hiring/cache responses.
        return request.app.state.market_access.require("candidate", "contacts", **refs).data


def process_deletion_request(session, event):
    from reverse_hr.market_cleanup import erase

    def scrub(subject):
        from reverse_hr.domains.hiring_trust import scrub as scrub_trust

        scrub_trust(session, subject)
        from reverse_hr.domains.hiring_dialogs import scrub_dialogs

        scrub_dialogs(session, subject)
        from reverse_hr.domains.hiring_ats import scrub as scrub_ats

        scrub_ats(session, subject)
        from reverse_hr.domains.hiring_vacancies import scrub_vacancies

        scrub_vacancies(session, subject)
        session.execute(
            delete(InvitationRevision).where(
                (InvitationRevision.candidate_id == subject)
                | (InvitationRevision.created_by == subject)
            )
        )
        session.execute(delete(Need).where(Need.created_by == subject))
        session.execute(
            delete(InvitationRow).where(
                (InvitationRow.candidate_id == subject) | (InvitationRow.created_by == subject)
            )
        )

    return erase(session, event, "hiring", HiringSubject, scrub)


@internal_router.post("/resume-permission", response_model=MarketReceipt)
def resume_permission(request: Request, body: MarketRequest, signature: Signature):
    def checker(session):
        from reverse_hr.auth import Principal
        from reverse_hr.domains.hiring_dialogs import blocked

        actor = Principal(body.actor_id, frozenset({"employer"}), False)
        try:
            row = invitation_guard(request, actor, body.invitation_id, session)
            if (
                row.candidate_id != str(body.candidate_id)
                or row.organization_id != str(body.organization_id)
                or row.status != "accepted"
                or blocked(session, row.candidate_id, row.organization_id)
            ):
                return None, 0
            request.app.state.market_access.require(
                "privacy",
                "contact-permission",
                candidate_id=body.candidate_id,
                organization_id=body.organization_id,
                invitation_id=body.invitation_id,
            )
            return {"invitation_id": str(body.invitation_id)}, row.version
        except HTTPException as exc:
            if exc.status_code in {403, 404, 409}:
                return None, 0
            raise

    return respond(
        request,
        body,
        signature,
        "hiring",
        "resume-permission",
        HiringNonce,
        {"candidate", "integration"},
        checker,
    )


@router.post("/invitation-drafts", response_model=InvitationView, status_code=201)
def draft_invitation(
    request: Request, actor: Actor, body: InvitationCreate, idempotency: CommandKey
):
    def guard(session):
        for subject in sorted({str(actor.subject), str(body.candidate_id)}):
            lock(session, HiringSubject, subject)
        member(request, actor, body.organization_id)
        request.app.state.processing_access.check(body.candidate_id)

    return execute(
        request.app.state.engine,
        actor.subject,
        "invitation_draft",
        idempotency,
        body.model_dump(mode="json"),
        lambda session: invitation_view(
            create_invitation(session, request, actor, body, draft=True)
        ),
        201,
        guard=guard,
        present=lambda session, value: invitation_view(
            session.get(InvitationRow, value["invitation_id"])
        ),
    )


@router.put("/invitations/{invitation_id}/draft", response_model=InvitationView)
def edit_draft(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    body: InvitationCreate,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        row = invitation_guard(request, actor, invitation_id, session)
        member(request, actor, UUID(row.organization_id))
        if (
            row.status != "draft"
            or row.candidate_id != str(body.candidate_id)
            or row.organization_id != str(body.organization_id)
        ):
            raise HTTPException(409)

    def change(session):
        row = session.get(InvitationRow, str(invitation_id))
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.spec, row.version = body.model_dump(mode="json"), row.version + 1
        record_terms(session, row)
        return invitation_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "edit_draft:" + str(invitation_id),
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        guard=guard,
        present=lambda session, _: invitation_view(session.get(InvitationRow, str(invitation_id))),
    )


@router.post("/invitations/{invitation_id}/send", response_model=InvitationView)
def send_draft(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        row = invitation_guard(request, actor, invitation_id, session)
        member(request, actor, UUID(row.organization_id))
        from reverse_hr.domains.hiring_dialogs import blocked

        if blocked(session, row.candidate_id, row.organization_id):
            raise HTTPException(409)
        request.app.state.market_access.require(
            "candidate", "profile", candidate_id=UUID(row.candidate_id)
        )

    def change(session):
        row = session.get(InvitationRow, str(invitation_id))
        if row.status != "draft" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.status, row.version = "sent", row.version + 1
        row.expires_at = datetime.now(UTC) + timedelta(days=row.spec["expires_in_days"])
        record_terms(session, row)
        emit(
            session,
            request,
            row.invitation_id,
            row.version,
            "invitation_sent",
            dict(
                invitation_id=invitation_id,
                candidate_id=UUID(row.candidate_id),
                organization_id=UUID(row.organization_id),
            ),
        )
        from reverse_hr.domains.hiring_dialogs import notify

        notify(session, request, row, row.candidate_id, "invitation_sent", actor.subject)
        return invitation_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "send_draft:" + str(invitation_id),
        idempotency,
        dict(version=if_match),
        change,
        guard=guard,
        present=lambda session, _: invitation_view(session.get(InvitationRow, str(invitation_id))),
    )


@router.post("/invitations/{invitation_id}/view", response_model=InvitationView)
def mark_viewed(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(InvitationRow, str(invitation_id))
        if (
            row.status not in {"sent", "viewed"}
            or utc(row.expires_at) <= datetime.now(UTC)
            or row.version != int(if_match.strip('"'))
        ):
            raise HTTPException(409)
        if row.status == "sent":
            row.status, row.version = "viewed", row.version + 1
            emit(
                session,
                request,
                row.invitation_id,
                row.version,
                "invitation_viewed",
                dict(
                    invitation_id=invitation_id,
                    candidate_id=actor.subject,
                    organization_id=UUID(row.organization_id),
                ),
            )
        return invitation_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "view:" + str(invitation_id),
        idempotency,
        dict(version=if_match),
        change,
        guard=lambda session: invitation_guard(request, actor, invitation_id, session, True),
        present=lambda session, _: invitation_view(session.get(InvitationRow, str(invitation_id))),
    )


@router.post(
    "/invitations/{invitation_id}/revisions", response_model=InvitationView, status_code=201
)
def revise_invitation(
    request: Request,
    actor: Actor,
    invitation_id: UUID,
    body: InvitationCreate,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        row = invitation_guard(request, actor, invitation_id, session)
        member(request, actor, UUID(row.organization_id))
        from reverse_hr.domains.hiring_dialogs import blocked

        if blocked(session, row.candidate_id, row.organization_id):
            raise HTTPException(409)
        if row.candidate_id != str(body.candidate_id) or row.organization_id != str(
            body.organization_id
        ):
            raise HTTPException(409)
        request.app.state.market_access.require(
            "candidate", "profile", candidate_id=body.candidate_id
        )

    def change(session):
        row = session.get(InvitationRow, str(invitation_id))
        if row.status not in {"sent", "viewed", "accepted"} or row.version != int(
            if_match.strip('"')
        ):
            raise HTTPException(409)
        if row.status != "accepted" and utc(row.expires_at) <= datetime.now(UTC):
            raise HTTPException(409)
        if row.spec == body.model_dump(mode="json"):
            raise HTTPException(409, "Terms are unchanged")
        # Grants identify a concrete invitation. A replacement never inherits the old grant.
        row.status, row.version = "revoked", row.version + 1
        emit(
            session,
            request,
            row.invitation_id,
            row.version,
            "invitation_revoked",
            dict(
                invitation_id=invitation_id,
                candidate_id=UUID(row.candidate_id),
                organization_id=UUID(row.organization_id),
            ),
        )
        replacement = create_invitation(
            session, request, actor, body, predecessor=str(invitation_id)
        )
        from reverse_hr.domains.hiring_vacancies import invitation_replaced

        invitation_replaced(session, request, actor, row, replacement)
        return invitation_view(replacement)

    return execute(
        request.app.state.engine,
        actor.subject,
        "revise:" + str(invitation_id),
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        201,
        guard=guard,
        present=lambda session, value: invitation_view(
            session.get(InvitationRow, value["invitation_id"])
        ),
    )


@router.get("/invitations/{invitation_id}/history", response_model=list[RevisionView])
def invitation_history(request: Request, actor: Actor, invitation_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = invitation_guard(request, actor, invitation_id, session)
        values = session.scalars(
            select(InvitationRevision)
            .where(InvitationRevision.invitation_id == row.invitation_id)
            .order_by(InvitationRevision.version)
            .limit(100)
        )
        return [
            RevisionView(
                invitation_id=item.invitation_id,
                version=item.version,
                predecessor_id=item.predecessor_id,
                terms=item.terms,
                recorded_at=utc(item.recorded_at),
            )
            for item in values
        ]
