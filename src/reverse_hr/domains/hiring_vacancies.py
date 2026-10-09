"""Moderated vacancies and candidate initiated applications; disclosure stays in Privacy."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract, Grade, SalaryRange
from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.hiring import (
    HiringBase,
    HiringSubject,
    InvitationRow,
    Need,
    create_invitation,
    emit,
    member,
    utc,
)
from reverse_hr.domains.hiring_dialogs import Notice, blocked
from reverse_hr.market_contracts import CandidateCard, InvitationCreate, NeedCommand, NoticeView
from reverse_hr.market_state import lock
from reverse_hr.matching_conditions import EmploymentConditions

VacancyStatus = Literal["draft", "submitted", "approved", "rejected", "published", "archived"]
ApplicationStatus = Literal[
    "submitted", "reviewing", "invited", "interview", "offer", "hired", "rejected", "withdrawn"
]
TERMINAL = {"hired", "rejected", "withdrawn"}
NEXT = {
    "submitted": {"reviewing", "rejected"},
    "reviewing": {"rejected"},
    "invited": {"interview", "rejected"},
    "interview": {"offer", "rejected"},
    "offer": {"hired", "rejected"},
}


class Vacancy(HiringBase):
    __tablename__ = "hiring_vacancies"
    vacancy_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    need_id: Mapped[str] = mapped_column(String(36), unique=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    spec: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    revision: Mapped[int]
    version: Mapped[int]


class VacancyDecision(HiringBase):
    __tablename__ = "hiring_vacancy_decisions"
    __table_args__ = (UniqueConstraint("vacancy_id", "revision"),)
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vacancy_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int]
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(2000))
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Application(HiringBase):
    __tablename__ = "hiring_applications"
    __table_args__ = (UniqueConstraint("vacancy_id", "candidate_id"),)
    application_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    vacancy_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    vacancy_version: Mapped[int]
    vacancy_snapshot: Mapped[dict] = mapped_column(JSON)
    invitation_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ApplicationChange(HiringBase):
    __tablename__ = "hiring_application_changes"
    __table_args__ = (UniqueConstraint("application_id", "version"),)
    change_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    application_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    changed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VacancyCommand(Contract):
    conditions: EmploymentConditions | None = None
    organization_id: UUID
    title: str = Field(min_length=1, max_length=200, pattern=r"\S")
    description: str = Field(min_length=1, max_length=5000, pattern=r"\S")
    employer_contact: str = Field(min_length=1, max_length=300, pattern=r"\S")
    salary: SalaryRange
    requirements: NeedCommand

    # The nested matching need cannot choose another organization or publication state.
    def normalized(self):
        if (
            self.requirements.organization_id != self.organization_id
            or self.requirements.status != "draft"
        ):
            raise HTTPException(
                422, "Requirements must be draft and belong to the vacancy organization"
            )
        conditions = self.conditions or self.requirements.conditions
        if (
            self.conditions
            and self.requirements.conditions
            and self.conditions != self.requirements.conditions
        ):
            raise HTTPException(422, "Vacancy and matching conditions must agree")
        if (
            conditions
            and conditions.salary
            and conditions.salary.model_dump() != self.salary.model_dump()
        ):
            raise HTTPException(422, "Vacancy and matching salary must agree")
        result = self.model_dump(mode="json")
        if conditions:
            if conditions.salary is None:
                conditions = EmploymentConditions(
                    **{**conditions.model_dump(), "salary": self.salary.model_dump()}
                )
            result["conditions"] = conditions.model_dump(mode="json")
            result["requirements"]["conditions"] = result["conditions"]
        return result


class VacancyView(VacancyCommand):
    vacancy_id: UUID
    need_id: UUID
    status: VacancyStatus
    revision: int
    version: int


class DecisionCommand(Contract):
    outcome: Literal["approved", "rejected"]
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class DecisionView(DecisionCommand):
    decision_id: UUID
    reviewer_id: UUID
    revision: int
    decided_at: datetime


class ApplyCommand(Contract):
    vacancy_version: int = Field(strict=True, ge=1)


class ApplicationView(Contract):
    application_id: UUID
    vacancy_id: UUID
    organization_id: UUID
    candidate_id: UUID
    vacancy_version: int
    vacancy_snapshot: VacancyView
    status: ApplicationStatus
    version: int
    invitation_id: UUID | None
    dialog_id: UUID | None
    invitation_status: (
        Literal["sent", "viewed", "accepted", "declined", "revoked", "expired"] | None
    )
    created_at: datetime


class StatusCommand(Contract):
    status: Literal["reviewing", "interview", "offer", "hired", "rejected"]


class InviteCommand(Contract):
    expires_in_days: int = Field(default=14, strict=True, ge=1, le=90)


class ApplicationPreview(Contract):
    vacancy: VacancyView
    shared_fields: list[str]
    contacts_disclosed: Literal[False] = False
    disclosure_requires_invitation_acceptance: Literal[True] = True


class ChangeView(Contract):
    status: ApplicationStatus
    version: int
    changed_at: datetime


router = APIRouter(prefix="/v1", tags=["vacancies-applications"])


def fences(request, actor, session, owners):
    for subject in sorted(set(owners) | {str(actor.subject)}):
        lock(session, HiringSubject, subject)
        request.app.state.processing_access.check(UUID(subject))


def owner_active(request, row):
    request.app.state.market_access.require(
        "employer",
        "membership",
        candidate_id=UUID(row.created_by),
        actor_id=UUID(row.created_by),
        organization_id=UUID(row.organization_id),
    )


def vacancy_guard(request, actor, session, vacancy_id, *, employer=False, review=False):
    row = session.get(Vacancy, str(vacancy_id))
    if row is None:
        raise HTTPException(404)
    decision = session.scalar(
        select(VacancyDecision).where(
            VacancyDecision.vacancy_id == row.vacancy_id, VacancyDecision.revision == row.revision
        )
    )
    owners = {row.created_by} | ({decision.reviewer_id} if decision else set())
    fences(request, actor, session, owners)
    row = session.scalar(
        select(Vacancy)
        .where(Vacancy.vacancy_id == str(vacancy_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    current = session.scalar(
        select(VacancyDecision)
        .where(
            VacancyDecision.vacancy_id == row.vacancy_id, VacancyDecision.revision == row.revision
        )
        .execution_options(populate_existing=True)
    )
    if current and current.reviewer_id not in owners | {str(actor.subject)}:
        raise HTTPException(409)
    if row.status in {"approved", "published"} and (not current or current.outcome != "approved"):
        raise HTTPException(409)
    if review:
        actor.require("company_moderator", mfa=True)
        if row.created_by == str(actor.subject):
            raise HTTPException(403)
        affiliation = request.app.state.market_access.fetch(
            "employer",
            "affiliation",
            candidate_id=actor.subject,
            actor_id=actor.subject,
            organization_id=UUID(row.organization_id),
        )
        if affiliation.allowed:
            raise HTTPException(403)
    elif employer:
        member(request, actor, UUID(row.organization_id))
    elif row.status != "published":
        # Owners can inspect private versions through the same detail endpoint.
        member(request, actor, UUID(row.organization_id))
    owner_active(request, row)
    return row


def vacancy_view(row):
    return VacancyView(
        **row.spec,
        vacancy_id=row.vacancy_id,
        need_id=row.need_id,
        status=row.status,
        revision=row.revision,
        version=row.version,
    ).model_dump(mode="json")


def sync_need(session, request, row):
    need = session.get(Need, row.need_id)
    need.spec = dict(
        row.spec["requirements"],
        status="published"
        if row.status == "published"
        else "closed"
        if row.status == "archived"
        else "draft",
    )
    need.version += 1
    emit(
        session,
        request,
        row.need_id,
        need.version,
        "need_changed",
        dict(
            need_id=UUID(row.need_id),
            organization_id=UUID(row.organization_id),
            actor_id=UUID(row.created_by),
        ),
    )
    emit(
        session,
        request,
        row.vacancy_id,
        row.version,
        "vacancy_changed",
        dict(
            vacancy_id=UUID(row.vacancy_id),
            organization_id=UUID(row.organization_id),
            actor_id=UUID(row.created_by),
        ),
    )


def vacancy_command(request, actor, vacancy_id, key, version, payload, change, *, review=False):
    def guard(session):
        vacancy_guard(request, actor, session, vacancy_id, employer=not review, review=review)

    def apply(session):
        row = session.get(Vacancy, str(vacancy_id))
        if row.version != int(version.strip('"')):
            raise HTTPException(409)
        change(session, row)
        row.version += 1
        sync_need(session, request, row)
        return {"vacancy_id": row.vacancy_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"vacancy:{vacancy_id}:{payload['action']}",
        key,
        dict(payload=payload, version=version),
        apply,
        guard=guard,
        present=lambda session, _: vacancy_view(session.get(Vacancy, str(vacancy_id))),
    )


@router.post("/vacancies", response_model=VacancyView, status_code=201)
def create_vacancy(request: Request, actor: Actor, body: VacancyCommand, idempotency: CommandKey):
    spec = body.normalized()

    def guard(session):
        member(request, actor, body.organization_id)
        fences(request, actor, session, set())

    def change(session):
        need = Need(
            need_id=str(uuid4()),
            organization_id=str(body.organization_id),
            created_by=str(actor.subject),
            spec=spec["requirements"],
            version=1,
        )
        row = Vacancy(
            vacancy_id=str(uuid4()),
            need_id=need.need_id,
            organization_id=need.organization_id,
            created_by=need.created_by,
            spec=spec,
            status="draft",
            revision=1,
            version=1,
        )
        session.add_all([need, row])
        emit(
            session,
            request,
            row.vacancy_id,
            1,
            "vacancy_changed",
            dict(
                vacancy_id=UUID(row.vacancy_id),
                organization_id=body.organization_id,
                actor_id=actor.subject,
            ),
        )
        return {"vacancy_id": row.vacancy_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_vacancy",
        idempotency,
        spec,
        change,
        201,
        guard=guard,
        present=lambda session, result: vacancy_view(session.get(Vacancy, result["vacancy_id"])),
    )


@router.put("/vacancies/{vacancy_id}", response_model=VacancyView)
def edit_vacancy(
    request: Request,
    actor: Actor,
    vacancy_id: UUID,
    body: VacancyCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    spec = body.normalized()

    def change(session, row):
        if row.organization_id != str(body.organization_id) or row.status == "archived":
            raise HTTPException(409)
        row.spec, row.status, row.revision = spec, "draft", row.revision + 1

    return vacancy_command(
        request, actor, vacancy_id, idempotency, if_match, dict(action="edit", body=spec), change
    )


@router.get("/vacancies", response_model=list[VacancyView])
def list_vacancies(
    request: Request,
    actor: Actor,
    organization_id: UUID | None = None,
    specialization: str | None = None,
    confirmed_grade: Grade | None = None,
    after: UUID | None = None,
):
    if organization_id:
        member(request, actor, organization_id)
    else:
        actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        query = select(Vacancy)
        query = (
            query.where(Vacancy.organization_id == str(organization_id))
            if organization_id
            else query.where(Vacancy.status == "published")
        )
        if specialization:
            query = query.where(
                Vacancy.spec["requirements"]["specialization"].as_string() == specialization
            )
        if confirmed_grade:
            query = query.where(
                Vacancy.spec["requirements"]["confirmed_grade"].as_string() == confirmed_grade.value
            )
        if after:
            query = query.where(Vacancy.vacancy_id > str(after))
        rows = list(session.scalars(query.order_by(Vacancy.vacancy_id).limit(50)))
        decisions = {
            row.vacancy_id: session.scalar(
                select(VacancyDecision).where(
                    VacancyDecision.vacancy_id == row.vacancy_id,
                    VacancyDecision.revision == row.revision,
                )
            )
            for row in rows
        }
        subjects = (
            {row.created_by for row in rows}
            | {str(actor.subject)}
            | {d.reviewer_id for d in decisions.values() if d}
        )
        states = {
            subject: lock(session, HiringSubject, subject, allow_blocked=True)
            for subject in sorted(subjects)
        }
        if states[str(actor.subject)].blocked:
            raise HTTPException(409)
        request.app.state.processing_access.check(actor.subject)
        if organization_id:
            member(request, actor, organization_id)
        result = []
        for row in rows:
            if states[row.created_by].blocked:
                continue
            decision = decisions[row.vacancy_id]
            if decision and states[decision.reviewer_id].blocked:
                continue
            if row.status in {"approved", "published"} and (
                not decision or decision.outcome != "approved"
            ):
                continue
            try:
                request.app.state.processing_access.check(UUID(row.created_by))
                if decision:
                    request.app.state.processing_access.check(UUID(decision.reviewer_id))
                owner_active(request, row)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                continue
            result.append(vacancy_view(row))
        return result


@router.get("/vacancies/{vacancy_id}", response_model=VacancyView)
def get_vacancy(request: Request, actor: Actor, vacancy_id: UUID):
    if not actor.roles & {"candidate", "employer"}:
        raise HTTPException(403)
    with Session(request.app.state.engine) as session, session.begin():
        return vacancy_view(vacancy_guard(request, actor, session, vacancy_id))


@router.get("/vacancy-reviews", response_model=list[VacancyView])
def review_queue(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("company_moderator", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(Vacancy).where(Vacancy.status == "submitted")
        if after:
            query = query.where(Vacancy.vacancy_id > str(after))
        rows = list(session.scalars(query.order_by(Vacancy.vacancy_id).limit(50)))
        fences(request, actor, session, {row.created_by for row in rows})
        return [vacancy_view(row) for row in rows]


@router.get("/vacancies/{vacancy_id}/reviews", response_model=list[DecisionView])
def reviews(request: Request, actor: Actor, vacancy_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        vacancy_guard(
            request,
            actor,
            session,
            vacancy_id,
            employer="employer" in actor.roles,
            review="employer" not in actor.roles,
        )
        rows = session.scalars(
            select(VacancyDecision)
            .where(VacancyDecision.vacancy_id == str(vacancy_id))
            .order_by(VacancyDecision.revision.desc())
            .limit(50)
        )
        return [
            DecisionView(
                decision_id=row.decision_id,
                reviewer_id=row.reviewer_id,
                revision=row.revision,
                outcome=row.outcome,
                reason=row.reason,
                decided_at=utc(row.decided_at),
            ).model_dump(mode="json")
            for row in rows
        ]


@router.post("/vacancies/{vacancy_id}/submit", response_model=VacancyView)
def submit_vacancy(
    request: Request,
    actor: Actor,
    vacancy_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session, row):
        if row.status != "draft":
            raise HTTPException(409)
        row.status = "submitted"

    return vacancy_command(
        request, actor, vacancy_id, idempotency, if_match, dict(action="submit"), change
    )


@router.post("/vacancies/{vacancy_id}/review", response_model=VacancyView)
def review_vacancy(
    request: Request,
    actor: Actor,
    vacancy_id: UUID,
    body: DecisionCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session, row):
        if row.status != "submitted":
            raise HTTPException(409)
        row.status = body.outcome
        session.add(
            VacancyDecision(
                decision_id=str(uuid4()),
                vacancy_id=row.vacancy_id,
                reviewer_id=str(actor.subject),
                revision=row.revision,
                outcome=body.outcome,
                reason=body.reason,
                decided_at=datetime.now(UTC),
            )
        )

    return vacancy_command(
        request,
        actor,
        vacancy_id,
        idempotency,
        if_match,
        dict(action="review", body=body.model_dump(mode="json")),
        change,
        review=True,
    )


@router.post("/vacancies/{vacancy_id}/publish", response_model=VacancyView)
def publish_vacancy(
    request: Request,
    actor: Actor,
    vacancy_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session, row):
        if row.status != "approved":
            raise HTTPException(409)
        row.status = "published"

    return vacancy_command(
        request, actor, vacancy_id, idempotency, if_match, dict(action="publish"), change
    )


@router.post("/vacancies/{vacancy_id}/archive", response_model=VacancyView)
def archive_vacancy(
    request: Request,
    actor: Actor,
    vacancy_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session, row):
        if row.status == "archived":
            raise HTTPException(409)
        row.status = "archived"

    return vacancy_command(
        request, actor, vacancy_id, idempotency, if_match, dict(action="archive"), change
    )


def application_view(session, row):
    invitation = session.get(InvitationRow, row.invitation_id) if row.invitation_id else None
    return ApplicationView(
        application_id=row.application_id,
        vacancy_id=row.vacancy_id,
        organization_id=row.organization_id,
        candidate_id=row.candidate_id,
        vacancy_version=row.vacancy_version,
        vacancy_snapshot=row.vacancy_snapshot,
        status=row.status,
        version=row.version,
        invitation_id=row.invitation_id,
        invitation_status=(
            "expired"
            if invitation.status in {"sent", "viewed"}
            and utc(invitation.expires_at) <= datetime.now(UTC)
            else invitation.status
        )
        if invitation
        else None,
        dialog_id=row.invitation_id if invitation and invitation.status == "accepted" else None,
        created_at=utc(row.created_at),
    ).model_dump(mode="json")


def application_guard(request, actor, session, application_id, *, candidate=False, employer=False):
    row = session.get(Application, str(application_id))
    if row is None:
        raise HTTPException(404)
    invitation = session.get(InvitationRow, row.invitation_id) if row.invitation_id else None
    owners = {row.candidate_id, row.created_by} | ({invitation.created_by} if invitation else set())
    fences(request, actor, session, owners)
    row = session.scalar(
        select(Application)
        .where(Application.application_id == str(application_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if employer or row.candidate_id != str(actor.subject):
        if candidate:
            raise HTTPException(404)
        member(request, actor, UUID(row.organization_id))
    else:
        actor.require("candidate")
    return row


def candidate_card(request, row):
    return CandidateCard.model_validate(
        request.app.state.market_access.require(
            "candidate", "profile", candidate_id=UUID(row.candidate_id)
        ).data
    )


def notify_application(session, request, row, recipient, kind, actor):
    notice = Notice(
        notice_id=str(uuid4()),
        invitation_id=None,
        application_id=row.application_id,
        recipient_id=str(recipient),
        author_id=str(actor.subject),
        kind=kind,
    )
    session.add(notice)
    emit(
        session,
        request,
        notice.notice_id,
        1,
        "notification_requested",
        dict(
            notice_id=UUID(notice.notice_id),
            recipient_id=UUID(str(recipient)),
            application_id=UUID(row.application_id),
            candidate_id=UUID(row.candidate_id),
            organization_id=UUID(row.organization_id),
            actor_id=actor.subject,
            creator_id=UUID(row.created_by),
        ),
    )


def changed(session, request, actor, row, *, recipient=None):
    session.add(
        ApplicationChange(
            change_id=str(uuid4()),
            application_id=row.application_id,
            actor_id=str(actor.subject),
            status=row.status,
            version=row.version,
            changed_at=datetime.now(UTC),
        )
    )
    emit(
        session,
        request,
        row.application_id,
        row.version,
        "application_changed",
        dict(
            application_id=UUID(row.application_id),
            vacancy_id=UUID(row.vacancy_id),
            candidate_id=UUID(row.candidate_id),
            organization_id=UUID(row.organization_id),
            actor_id=actor.subject,
        ),
    )
    notify_application(
        session,
        request,
        row,
        recipient or row.candidate_id,
        "application_submitted" if row.version == 1 else "application_status_changed",
        actor,
    )


@router.get("/vacancies/{vacancy_id}/application-preview", response_model=ApplicationPreview)
def preview_application(request: Request, actor: Actor, vacancy_id: UUID):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        row = vacancy_guard(request, actor, session, vacancy_id)
        if row.status != "published" or blocked(session, actor.subject, row.organization_id):
            raise HTTPException(409)
        return ApplicationPreview(
            vacancy=vacancy_view(row),
            shared_fields=[
                "candidate_id",
                "display_name",
                "specialization",
                "declared_skills",
                "confirmed_grade",
                "decision_id",
                "version",
                "demo",
            ],
        )


@router.post(
    "/vacancies/{vacancy_id}/applications", response_model=ApplicationView, status_code=201
)
def apply_vacancy(
    request: Request, actor: Actor, vacancy_id: UUID, body: ApplyCommand, idempotency: CommandKey
):
    actor.require("candidate")

    def guard(session):
        row = vacancy_guard(request, actor, session, vacancy_id)
        if blocked(session, actor.subject, row.organization_id):
            raise HTTPException(409)
        request.app.state.market_access.require("candidate", "profile", candidate_id=actor.subject)

    def change(session):
        vacancy = session.get(Vacancy, str(vacancy_id))
        if vacancy.status != "published" or vacancy.version != body.vacancy_version:
            raise HTTPException(409)
        row = Application(
            application_id=str(uuid4()),
            vacancy_id=str(vacancy_id),
            organization_id=vacancy.organization_id,
            created_by=vacancy.created_by,
            candidate_id=str(actor.subject),
            vacancy_version=vacancy.version,
            vacancy_snapshot=vacancy_view(vacancy),
            status="submitted",
            version=1,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        changed(session, request, actor, row, recipient=row.created_by)
        return {"application_id": row.application_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"apply:{vacancy_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, value: application_view(
            session, session.get(Application, value["application_id"])
        ),
    )


@router.get("/applications", response_model=list[ApplicationView])
def list_applications(
    request: Request,
    actor: Actor,
    organization_id: UUID | None = None,
    vacancy_id: UUID | None = None,
    after: UUID | None = None,
):
    if organization_id:
        member(request, actor, organization_id)
    else:
        actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        query = (
            select(Application).where(Application.organization_id == str(organization_id))
            if organization_id
            else select(Application).where(Application.candidate_id == str(actor.subject))
        )
        if vacancy_id:
            query = query.where(Application.vacancy_id == str(vacancy_id))
        if after:
            query = query.where(Application.application_id > str(after))
        rows = list(session.scalars(query.order_by(Application.application_id).limit(50)))
        invitations = {
            row.invitation_id: session.get(InvitationRow, row.invitation_id)
            for row in rows
            if row.invitation_id
        }
        subjects = (
            {str(actor.subject)}
            | {row.candidate_id for row in rows}
            | {row.created_by for row in rows}
            | {row.created_by for row in invitations.values() if row}
        )
        states = {
            subject: lock(session, HiringSubject, subject, allow_blocked=True)
            for subject in sorted(subjects)
        }
        if states[str(actor.subject)].blocked:
            raise HTTPException(409)
        request.app.state.processing_access.check(actor.subject)
        if organization_id:
            member(request, actor, organization_id)
        result = []
        for row in rows:
            invitation = invitations.get(row.invitation_id)
            owners = {row.candidate_id, row.created_by} | (
                {invitation.created_by} if invitation else set()
            )
            if any(states[owner].blocked for owner in owners):
                continue
            try:
                for owner in sorted(owners):
                    request.app.state.processing_access.check(UUID(owner))
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
                continue
            result.append(application_view(session, row))
        return result


@router.get("/applications/{application_id}", response_model=ApplicationView)
def get_application(request: Request, actor: Actor, application_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        return application_view(session, application_guard(request, actor, session, application_id))


@router.get("/applications/{application_id}/history", response_model=list[ChangeView])
def application_history(request: Request, actor: Actor, application_id: UUID, after: int = 0):
    if after < 0:
        raise HTTPException(422)
    with Session(request.app.state.engine) as session, session.begin():
        application_guard(request, actor, session, application_id)
        rows = session.scalars(
            select(ApplicationChange)
            .where(
                ApplicationChange.application_id == str(application_id),
                ApplicationChange.version > after,
            )
            .order_by(ApplicationChange.version)
            .limit(50)
        )
        return [
            ChangeView(status=row.status, version=row.version, changed_at=utc(row.changed_at))
            for row in rows
        ]


@router.get("/applications/{application_id}/candidate", response_model=CandidateCard)
def application_candidate(request: Request, actor: Actor, application_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = application_guard(request, actor, session, application_id, employer=True)
        if row.status in {"withdrawn", "rejected"} or blocked(
            session, row.candidate_id, row.organization_id
        ):
            raise HTTPException(409)
        return candidate_card(request, row)


def application_command(
    request, actor, application_id, key, version, payload, action, *, candidate=False
):
    def guard(session):
        row = application_guard(
            request, actor, session, application_id, candidate=candidate, employer=not candidate
        )
        if not candidate and blocked(session, row.candidate_id, row.organization_id):
            raise HTTPException(409)

    def change(session):
        row = session.get(Application, str(application_id))
        if row.version != int(version.strip('"')) or row.status in TERMINAL:
            raise HTTPException(409)
        action(session, row)
        row.version += 1
        changed(
            session,
            request,
            actor,
            row,
            recipient=row.created_by if candidate else row.candidate_id,
        )
        return {"application_id": row.application_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"application:{application_id}:{payload['action']}",
        key,
        dict(payload=payload, version=version),
        change,
        guard=guard,
        present=lambda session, _: application_view(
            session, session.get(Application, str(application_id))
        ),
    )


def close_invitation(session, request, row):
    invitation = session.get(InvitationRow, row.invitation_id) if row.invitation_id else None
    if invitation and invitation.status in {"sent", "viewed", "accepted"}:
        invitation.status, invitation.version = "revoked", invitation.version + 1
        emit(
            session,
            request,
            invitation.invitation_id,
            invitation.version,
            "invitation_revoked",
            dict(
                invitation_id=UUID(invitation.invitation_id),
                candidate_id=UUID(row.candidate_id),
                organization_id=UUID(row.organization_id),
            ),
        )


@router.post("/applications/{application_id}/status", response_model=ApplicationView)
def application_status(
    request: Request,
    actor: Actor,
    application_id: UUID,
    body: StatusCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def action(session, row):
        if body.status not in NEXT.get(row.status, set()):
            raise HTTPException(409)
        if body.status in {"interview", "offer", "hired"}:
            invitation = session.get(InvitationRow, row.invitation_id)
            if not invitation or invitation.status != "accepted":
                raise HTTPException(409)
            request.app.state.market_access.require(
                "privacy",
                "contact-permission",
                candidate_id=UUID(row.candidate_id),
                organization_id=UUID(row.organization_id),
                invitation_id=UUID(row.invitation_id),
            )
        row.status = body.status
        if body.status == "rejected":
            close_invitation(session, request, row)

    return application_command(
        request,
        actor,
        application_id,
        idempotency,
        if_match,
        dict(action="status", body=body.model_dump(mode="json")),
        action,
    )


@router.post("/applications/{application_id}/withdraw", response_model=ApplicationView)
def withdraw_application(
    request: Request,
    actor: Actor,
    application_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def action(session, row):
        row.status = "withdrawn"
        close_invitation(session, request, row)

    return application_command(
        request,
        actor,
        application_id,
        idempotency,
        if_match,
        dict(action="withdraw"),
        action,
        candidate=True,
    )


@router.post("/applications/{application_id}/invite", response_model=ApplicationView)
def invite_application(
    request: Request,
    actor: Actor,
    application_id: UUID,
    body: InviteCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def action(session, row):
        if row.status not in {"submitted", "reviewing"} or row.invitation_id:
            raise HTTPException(409)
        candidate_card(request, row)
        snapshot = row.vacancy_snapshot
        body_invite = InvitationCreate(
            organization_id=row.organization_id,
            candidate_id=row.candidate_id,
            description=snapshot["description"],
            employer_contact=snapshot["employer_contact"],
            salary=snapshot["salary"],
            conditions=snapshot.get("conditions"),
            expires_in_days=body.expires_in_days,
        )
        invitation = create_invitation(session, request, actor, body_invite)
        row.invitation_id, row.status = invitation.invitation_id, "invited"

    return application_command(
        request,
        actor,
        application_id,
        idempotency,
        if_match,
        dict(action="invite", body=body.model_dump(mode="json")),
        action,
    )


def invitation_replaced(session, request, actor, previous, replacement):
    row = session.scalar(
        select(Application)
        .where(Application.invitation_id == previous.invitation_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row is None:
        return
    if row.status in TERMINAL or (
        row.candidate_id != replacement.candidate_id
        or row.organization_id != replacement.organization_id
    ):
        raise HTTPException(409, "Cannot replace this application invitation")
    # Prior interviews remain factual; further actions require acceptance of the new terms.
    row.invitation_id = replacement.invitation_id
    row.version += 1
    changed(session, request, actor, row, recipient=row.candidate_id)


def invitation_closed(session, request, actor, invitation):
    row = session.scalar(
        select(Application)
        .where(Application.invitation_id == invitation.invitation_id)
        .with_for_update()
    )
    if row is not None and row.status not in TERMINAL:
        row.status = "withdrawn" if invitation.status == "declined" else "rejected"
        row.version += 1
        changed(
            session,
            request,
            actor,
            row,
            recipient=row.created_by if invitation.status == "declined" else row.candidate_id,
        )


def application_notice(request, session, notice):
    row = session.get(Application, notice.application_id)
    if row is None:
        return None, 0
    subjects = {notice.recipient_id, notice.author_id, row.candidate_id, row.created_by}
    for subject in sorted(subjects):
        if lock(session, HiringSubject, subject, allow_blocked=True).blocked:
            return None, 0
        request.app.state.processing_access.check(UUID(subject))
    if blocked(session, row.candidate_id, row.organization_id):
        return None, 0
    if notice.recipient_id != row.candidate_id:
        permission = request.app.state.market_access.fetch(
            "employer",
            "membership",
            candidate_id=UUID(notice.recipient_id),
            actor_id=UUID(notice.recipient_id),
            organization_id=UUID(row.organization_id),
        )
        if not permission.allowed:
            return None, 0
    return NoticeView(
        creator_id=row.created_by,
        candidate_id=row.candidate_id,
        author_id=notice.author_id,
        notice_id=notice.notice_id,
        recipient_id=notice.recipient_id,
        application_id=row.application_id,
        kind=notice.kind,
    ).model_dump(mode="json"), 1


def scrub_vacancies(session, subject):
    affected = list(
        session.scalars(
            select(Application.application_id).where(
                (Application.candidate_id == subject)
                | (Application.created_by == subject)
                | Application.invitation_id.in_(
                    select(InvitationRow.invitation_id).where(InvitationRow.created_by == subject)
                )
            )
        )
    )
    reviewed = list(
        session.scalars(
            select(VacancyDecision.vacancy_id)
            .join(Vacancy, Vacancy.vacancy_id == VacancyDecision.vacancy_id)
            .where(
                VacancyDecision.reviewer_id == subject, VacancyDecision.revision == Vacancy.revision
            )
        )
    )
    invitation_ids = list(
        session.scalars(
            select(Application.invitation_id).where(
                Application.application_id.in_(affected), Application.invitation_id.is_not(None)
            )
        )
    )
    for row in session.scalars(select(Vacancy).where(Vacancy.vacancy_id.in_(reviewed))):
        if row.status in {"approved", "published"}:
            row.status, row.version = "draft", row.version + 1
            need = session.get(Need, row.need_id)
            need.spec, need.version = dict(need.spec, status="draft"), need.version + 1
    notice_ids = list(
        session.scalars(select(Notice.notice_id).where(Notice.application_id.in_(affected)))
    )
    vacancies = list(
        session.scalars(select(Vacancy.vacancy_id).where(Vacancy.created_by == subject))
    )
    for ref in affected + notice_ids + vacancies + invitation_ids:
        session.execute(
            delete(IdempotencyRecord).where(
                IdempotencyRecord.response.contains(ref) | IdempotencyRecord.operation.contains(ref)
            )
        )
    session.execute(
        delete(Outbox).where(
            Outbox.envelope["aggregate_id"]
            .as_string()
            .in_(affected + notice_ids + vacancies + invitation_ids)
        )
    )
    session.execute(delete(Notice).where(Notice.application_id.in_(affected)))
    session.execute(
        delete(ApplicationChange).where(
            ApplicationChange.application_id.in_(affected) | (ApplicationChange.actor_id == subject)
        )
    )
    session.execute(delete(Application).where(Application.application_id.in_(affected)))
    session.execute(delete(InvitationRow).where(InvitationRow.invitation_id.in_(invitation_ids)))
    session.execute(
        delete(VacancyDecision).where(
            VacancyDecision.vacancy_id.in_(vacancies) | (VacancyDecision.reviewer_id == subject)
        )
    )
    session.execute(delete(Vacancy).where(Vacancy.created_by == subject))
