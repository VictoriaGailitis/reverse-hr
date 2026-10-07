"""Consent-gated candidate projection and reproducible requirement snapshots."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import JSON, String, delete, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.commands import CommandKey, execute
from reverse_hr.contracts import Contract, Grade
from reverse_hr.db import consume_once
from reverse_hr.market_contracts import CandidateCard, NeedView
from reverse_hr.market_state import SubjectColumns, lock
from reverse_hr.test_suites import digest

RANKING_VERSION = "confirmed-grade-declared-skills-v1"


class MatchingBase(DeclarativeBase):
    pass


class MatchingSubject(SubjectColumns, MatchingBase):
    __tablename__ = "matching_subjects"


class Projection(MatchingBase):
    __tablename__ = "matching_candidates"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    revision: Mapped[int]
    card: Mapped[dict | None] = mapped_column(JSON)


class MatchSnapshot(MatchingBase):
    __tablename__ = "matching_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    requested_by: Mapped[str] = mapped_column(String(36), index=True)
    need_author: Mapped[str] = mapped_column(String(36), index=True)
    query: Mapped[dict] = mapped_column(JSON)
    need_digest: Mapped[str] = mapped_column(String(64))
    matches: Mapped[list] = mapped_column(JSON)
    next_cursor: Mapped[str | None] = mapped_column(String(36))


class MatchQuery(Contract):
    organization_id: UUID
    need_id: UUID
    mode: Literal["production", "demo"] = "production"
    after: UUID | None = None


class MatchedCandidate(CandidateCard):
    explanation: str
    score: int = Field(ge=0, le=100)
    ranking_version: Literal["confirmed-grade-declared-skills-v1"] = RANKING_VERSION


class MatchResult(Contract):
    snapshot_id: UUID
    mode: Literal["production", "demo"]
    matches: list[MatchedCandidate]
    next_cursor: UUID | None


router = APIRouter(prefix="/v1/matches", tags=["matching"])


def card_from(receipt, candidate):
    if not receipt.allowed:
        return None
    card = CandidateCard.model_validate(receipt.data)
    if card.candidate_id != candidate or card.version != receipt.revision:
        raise HTTPException(503)
    return card


def process_profile_change(session, event, access):
    candidate_event = event.producer == "candidate" and event.event_type in {
        "candidate.profile_created.v1",
        "candidate.profile_updated.v1",
    }
    consent_event = event.producer == "privacy" and event.event_type == "privacy.consent_revoked.v1"
    if (
        not (candidate_event or consent_event)
        or set(event.payload)
        != ({"candidate_id"} if candidate_event else {"candidate_id", "consent_id"})
        or event.aggregate_id != event.payload["candidate_id" if candidate_event else "consent_id"]
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)
    subject = event.payload["candidate_id"]
    receipt = access.fetch("candidate", "profile", candidate_id=subject)
    card = card_from(receipt, subject)
    if candidate_event and receipt.revision < event.aggregate_version and card is not None:
        raise HTTPException(503)

    def apply(session, event):
        state = lock(session, MatchingSubject, subject, allow_blocked=True)
        if state.blocked:
            return
        row = session.get(Projection, str(subject))
        if row is None:
            row = Projection(candidate_id=str(subject), revision=0)
            session.add(row)
        if not receipt.allowed:
            row.card, row.revision = None, max(row.revision, receipt.revision)
            return
        if receipt.revision < row.revision:
            return
        access.check(subject)
        data = card.model_dump(mode="json")
        if row.card is not None and receipt.revision == row.revision and row.card != data:
            raise HTTPException(409)
        row.card, row.revision = data, receipt.revision

    return consume_once(session, "matching.profile_change", event, apply)


def need_for(request, actor, query):
    actor.require("employer")
    receipt = request.app.state.market_access.require(
        "hiring",
        "need",
        candidate_id=actor.subject,
        actor_id=actor.subject,
        organization_id=query.organization_id,
        need_id=query.need_id,
    )
    need = NeedView.model_validate(receipt.data)
    if (
        need.need_id != query.need_id
        or need.organization_id != query.organization_id
        or need.version != receipt.revision
    ):
        raise HTTPException(503)
    return need


def rank(card, need, mode):
    if (
        card.confirmed_grade is None
        or card.decision_id is None
        or (mode == "production" and card.demo)
        or card.specialization != need.specialization
        or not set(need.required_skills) <= set(card.declared_skills)
    ):
        return None
    distance = list(Grade).index(card.confirmed_grade) - list(Grade).index(need.confirmed_grade)
    if distance < 0:
        return None
    return MatchedCandidate(
        **card.model_dump(),
        score=100 - 10 * distance,
        explanation="Confirmed specialization/grade meets the need; "
        "required skills match candidate declarations. "
        "Skills are not independently verified; grade distance=" + str(distance),
    ).model_dump(mode="json")


@router.post("", response_model=MatchResult, status_code=201)
def find(request: Request, actor: Actor, body: MatchQuery, idempotency: CommandKey):
    need = need_for(request, actor, body)
    with Session(request.app.state.engine) as session:
        query = select(Projection).where(Projection.card["candidate_id"].as_string().is_not(None))
        if body.after:
            query = query.where(Projection.candidate_id > str(body.after))
        rows = list(session.scalars(query.order_by(Projection.candidate_id).limit(201)))
        ids = [UUID(row.candidate_id) for row in rows[:200]]
        next_cursor = str(ids[-1]) if len(rows) > 200 else None
    matches = []
    for subject in ids:
        receipt = request.app.state.market_access.fetch(
            "candidate", "profile", candidate_id=subject
        )
        card = card_from(receipt, subject)
        if card:
            value = rank(card, need, body.mode)
            if value:
                matches.append(value)
    matches.sort(key=lambda row: (-row["score"], row["candidate_id"]))

    def guard(session):
        for subject in sorted(
            {str(actor.subject), str(need.created_by)} | {row["candidate_id"] for row in matches}
        ):
            lock(session, MatchingSubject, subject)
        if digest(need_for(request, actor, body)) != digest(need):
            raise HTTPException(409)

    def change(session):
        row = MatchSnapshot(
            snapshot_id=str(uuid4()),
            requested_by=str(actor.subject),
            need_author=str(need.created_by),
            query=body.model_dump(mode="json"),
            need_digest=digest(need),
            matches=matches,
            next_cursor=next_cursor,
        )
        session.add(row)
        return {"snapshot_id": row.snapshot_id}

    def present(session, result):
        return render(request, actor, session.get(MatchSnapshot, result["snapshot_id"]))

    return execute(
        request.app.state.engine,
        actor.subject,
        "find_matches",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


def render(request, actor, row):
    if row is None or row.requested_by != str(actor.subject):
        raise HTTPException(404)
    query = MatchQuery.model_validate(row.query)
    need = need_for(request, actor, query)
    if digest(need) != row.need_digest:
        raise HTTPException(409)
    result = []
    for match in row.matches:
        receipt = request.app.state.market_access.fetch(
            "candidate", "profile", candidate_id=UUID(match["candidate_id"])
        )
        card = card_from(receipt, UUID(match["candidate_id"]))
        if card is not None and card.version == match["version"]:
            # Any mismatch, withdrawal or changed criteria suppresses stale sensitive fields.
            current = rank(card, need, query.mode)
            if current == match:
                result.append(match)
    return MatchResult(
        snapshot_id=row.snapshot_id, mode=query.mode, matches=result, next_cursor=row.next_cursor
    ).model_dump(mode="json")


@router.get("/{snapshot_id}", response_model=MatchResult)
def get_snapshot(request: Request, actor: Actor, snapshot_id: UUID):
    actor.require("employer")
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, MatchingSubject, actor.subject)
        return render(request, actor, session.get(MatchSnapshot, str(snapshot_id)))


def process_deletion_request(session, event):
    from reverse_hr.market_cleanup import erase

    def scrub(subject):
        session.execute(delete(Projection).where(Projection.candidate_id == subject))
        # Erase historical queries containing this subject, including cached disclosures.
        for row in session.scalars(select(MatchSnapshot)):
            if (
                row.requested_by == subject
                or row.need_author == subject
                or any(m["candidate_id"] == subject for m in row.matches)
            ):
                session.delete(row)

    return erase(session, event, "matching", MatchingSubject, scrub)
