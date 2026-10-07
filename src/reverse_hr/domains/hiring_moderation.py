"""Independent human complaint review, bounded evidence and immutable decisions."""

from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from pydantic import Field
from sqlalchemy import DateTime, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.contracts import Contract
from reverse_hr.domains.hiring import HiringBase, HiringSubject, InvitationRow, emit, router, utc
from reverse_hr.domains.hiring_dialogs import Complaint, Message, MessageView, message_view
from reverse_hr.market_state import lock

Outcome = Literal["upheld", "dismissed"]


class ComplaintCase(HiringBase):
    __tablename__ = "hiring_complaint_cases"
    complaint_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]


class ComplaintDecision(HiringBase):
    __tablename__ = "hiring_complaint_decisions"
    __table_args__ = (UniqueConstraint("complaint_id", "version"),)
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    complaint_id: Mapped[str] = mapped_column(String(36), index=True)
    reviewer_id: Mapped[str] = mapped_column(String(36), index=True)
    outcome: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(String(2000))
    version: Mapped[int]
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class DecisionCommand(Contract):
    outcome: Outcome
    reason: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class DecisionView(DecisionCommand):
    decision_id: UUID
    reviewer_id: UUID
    decided_at: datetime
    version: int


class CaseSummary(Contract):
    complaint_id: UUID
    dialog_id: UUID
    status: Literal["open", "upheld", "dismissed"]
    version: int
    created_at: datetime


class CaseDetail(CaseSummary):
    reason: str
    message: MessageView | None
    decisions: list[DecisionView]


def related(session, complaint_id):
    complaint = session.get(Complaint, str(complaint_id))
    case = session.get(ComplaintCase, str(complaint_id))
    if complaint is None or case is None:
        raise HTTPException(404)
    invitation = session.get(InvitationRow, complaint.dialog_id)
    if invitation is None:
        raise HTTPException(404)
    message = session.get(Message, complaint.message_id) if complaint.message_id else None
    if complaint.message_id and (message is None or message.dialog_id != complaint.dialog_id):
        raise HTTPException(409)
    decisions = list(
        session.scalars(
            select(ComplaintDecision)
            .where(ComplaintDecision.complaint_id == str(complaint_id))
            .order_by(ComplaintDecision.version)
        )
    )
    subjects = {complaint.author_id, invitation.candidate_id, invitation.created_by}
    if message:
        subjects.add(message.author_id)
    subjects |= {d.reviewer_id for d in decisions}
    return complaint, case, invitation, message, decisions, subjects


def authorize(request, actor, session, data):
    complaint, _, invitation, message, _, subjects = data
    actor.require("company_moderator", mfa=True)
    if str(actor.subject) in {complaint.author_id, invitation.created_by} or (
        message and str(actor.subject) == message.author_id
    ):
        raise HTTPException(403)
    for subject in subjects | {str(actor.subject)}:
        state = session.get(HiringSubject, subject)
        if state is None or state.blocked:
            raise HTTPException(409)
        request.app.state.processing_access.check(UUID(subject))
    affiliated = request.app.state.market_access.fetch(
        "employer",
        "affiliation",
        candidate_id=actor.subject,
        actor_id=actor.subject,
        organization_id=UUID(invitation.organization_id),
    )
    if affiliated.allowed:
        raise HTTPException(403)


def guard_case(request, actor, session, complaint_id):
    actor.require("company_moderator", mfa=True)
    data = related(session, complaint_id)
    for subject in sorted(data[-1] | {str(actor.subject)}):
        lock(session, HiringSubject, subject)
    authorize(request, actor, session, data)
    case = session.scalar(
        select(ComplaintCase)
        .where(ComplaintCase.complaint_id == str(complaint_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if case is None:
        raise HTTPException(404)
    refreshed = related(session, complaint_id)
    if not refreshed[-1].issubset(data[-1] | {str(actor.subject)}):
        raise HTTPException(409)
    authorize(request, actor, session, refreshed)
    return refreshed


def summary(complaint, case):
    return CaseSummary(
        complaint_id=complaint.complaint_id,
        dialog_id=complaint.dialog_id,
        status=case.status,
        version=case.version,
        created_at=utc(complaint.created_at),
    ).model_dump(mode="json")


def decision_view(row):
    return DecisionView(
        decision_id=row.decision_id,
        reviewer_id=row.reviewer_id,
        outcome=row.outcome,
        reason=row.reason,
        version=row.version,
        decided_at=utc(row.decided_at),
    ).model_dump(mode="json")


def detail(session, complaint_id):
    complaint, case, _, message, decisions, _ = related(session, complaint_id)
    return CaseDetail(
        **summary(complaint, case),
        reason=complaint.reason,
        message=message_view(message) if message else None,
        decisions=[decision_view(d) for d in decisions],
    ).model_dump(mode="json")


@router.get("/hiring-complaints", response_model=list[CaseSummary])
def queue(
    request: Request,
    actor: Actor,
    status: Literal["open", "upheld", "dismissed"] = "open",
    after: UUID | None = None,
):
    actor.require("company_moderator", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        query = select(ComplaintCase).where(ComplaintCase.status == status)
        if after:
            query = query.where(ComplaintCase.complaint_id > str(after))
        cases = list(session.scalars(query.order_by(ComplaintCase.complaint_id).limit(50)))
        rows = [related(session, case.complaint_id) for case in cases]
        subjects = {str(actor.subject)} | {subject for row in rows for subject in row[-1]}
        for subject in sorted(subjects):
            lock(session, HiringSubject, subject, allow_blocked=True)
        lock(session, HiringSubject, actor.subject)
        result = []
        for data in rows:
            try:
                session.refresh(data[1])
                data = related(session, data[0].complaint_id)
                if not data[-1].issubset(subjects) or data[1].status != status:
                    continue
                authorize(request, actor, session, data)
            except HTTPException as exc:
                if exc.status_code not in {403, 409}:
                    raise
                continue
            result.append(summary(data[0], data[1]))
        return result


@router.get("/hiring-complaints/{complaint_id}", response_model=CaseDetail)
def get_case(request: Request, actor: Actor, complaint_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        guard_case(request, actor, session, complaint_id)
        return detail(session, complaint_id)


@router.post("/hiring-complaints/{complaint_id}/decisions", response_model=CaseDetail)
def decide(
    request: Request,
    actor: Actor,
    complaint_id: UUID,
    body: DecisionCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        guard_case(request, actor, session, complaint_id)

    def change(session):
        complaint, case, invitation, _, _, _ = related(session, complaint_id)
        if case.status != "open" or case.version != int(if_match.strip('"')):
            raise HTTPException(409)
        case.status, case.version = body.outcome, case.version + 1
        decision = ComplaintDecision(
            decision_id=str(uuid4()),
            complaint_id=str(complaint_id),
            reviewer_id=str(actor.subject),
            outcome=body.outcome,
            reason=body.reason,
            version=case.version,
            decided_at=datetime.now(UTC),
        )
        session.add(decision)
        emit(
            session,
            request,
            complaint_id,
            case.version,
            "complaint_decided",
            {
                "complaint_id": complaint_id,
                "decision_id": UUID(decision.decision_id),
                "candidate_id": UUID(invitation.candidate_id),
                "reviewer_id": actor.subject,
            },
        )
        session.flush()
        return {"complaint_id": str(complaint_id)}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"complaint_decision:{complaint_id}",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=guard,
        present=lambda session, _: detail(session, complaint_id),
    )


@router.get("/dialogs/{dialog_id}/complaints/{complaint_id}", response_model=CaseSummary)
def own_case(request: Request, actor: Actor, dialog_id: UUID, complaint_id: UUID):
    from reverse_hr.domains.hiring_dialogs import dialog_guard

    with Session(request.app.state.engine) as session, session.begin():
        complaint = session.get(Complaint, str(complaint_id))
        if (
            complaint is None
            or complaint.dialog_id != str(dialog_id)
            or complaint.author_id != str(actor.subject)
        ):
            raise HTTPException(404)
        data = related(session, complaint_id)
        dialog_guard(request, actor, dialog_id, session, communication=False, authors=data[-1])
        case = session.get(ComplaintCase, str(complaint_id))
        if case is None:
            raise HTTPException(404)
        return summary(complaint, case)
