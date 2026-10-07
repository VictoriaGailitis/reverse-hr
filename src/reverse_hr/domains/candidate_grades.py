"""Idempotent private grade history, partitioned by specialization."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.confirmed_grade_access import DecisionSummary
from reverse_hr.contracts import Grade
from reverse_hr.db import consume_once
from reverse_hr.domains.candidate import CandidateBase, CandidateProfile, router, subject_lock


class CandidateDecision(CandidateBase):
    __tablename__ = "candidate_grade_history"
    decision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    reviewer_id: Mapped[str] = mapped_column(String(36))
    session_version: Mapped[int]
    summary: Mapped[dict] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class HistoryItem(DecisionSummary):
    decision_id: UUID
    session_id: UUID


def current_grade(session, candidate, specialization):
    grades = [
        DecisionSummary.model_validate(row.summary).target_grade
        for row in session.scalars(
            select(CandidateDecision).where(CandidateDecision.candidate_id == str(candidate))
        )
        if row.summary["specialization"] == specialization and row.summary["status"] == "confirmed"
    ]
    return max(grades, key=lambda g: list(Grade).index(g)) if grades else None


@router.get("/me/grade-history", response_model=list[HistoryItem])
def history(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        rows = session.scalars(
            select(CandidateDecision).where(CandidateDecision.candidate_id == str(actor.subject))
        )
        result = [
            HistoryItem(**row.summary, decision_id=row.decision_id, session_id=row.session_id)
            for row in rows
        ]
        return sorted(
            result, key=lambda item: (item.decided_at, str(item.decision_id)), reverse=True
        )


def process_grade_decision(session, event, access):
    if (
        event.producer != "assessment"
        or event.event_type != "assessment.grade_decision_recorded.v1"
        or set(event.payload) != {"candidate_id", "session_id", "decision_id", "reviewer_id"}
        or event.aggregate_id != event.payload["session_id"]
        or event.aggregate_version < 2
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)
    # Fetch before locking Candidate: RPC never executes with a local subject lock.
    summary = access.fetch(**event.payload, session_version=event.aggregate_version)

    def apply(session, event):
        candidate = event.payload["candidate_id"]
        subject_lock(session, candidate)
        access.check(candidate)
        existing = session.get(CandidateDecision, str(event.payload["decision_id"]))
        refs = {k: str(event.payload[k]) for k in ("candidate_id", "session_id", "reviewer_id")}
        if existing:
            if (
                any(getattr(existing, k) != v for k, v in refs.items())
                or existing.session_version != event.aggregate_version
                or existing.summary != summary.model_dump(mode="json")
            ):
                raise HTTPException(409)
            return
        profile = session.get(CandidateProfile, str(candidate))
        before = current_grade(session, candidate, profile.specialization) if profile else None
        session.add(
            CandidateDecision(
                decision_id=str(event.payload["decision_id"]),
                **refs,
                session_version=event.aggregate_version,
                summary=summary.model_dump(mode="json"),
                received_at=datetime.now(UTC),
            )
        )
        session.flush()
        if profile and before != current_grade(session, candidate, profile.specialization):
            profile.version += 1
            from reverse_hr.domains.candidate_market import emit_profile

            emit_profile(session, profile, event.correlation_id)

    return consume_once(session, "candidate.grade_decision", event, apply)
