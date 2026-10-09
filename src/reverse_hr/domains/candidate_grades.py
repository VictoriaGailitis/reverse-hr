"""Idempotent private grade history, partitioned by specialization."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from fastapi import HTTPException, Request
from sqlalchemy import JSON, DateTime, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.auth import Actor
from reverse_hr.confirmed_grade_access import DecisionSummary
from reverse_hr.contracts import Grade
from reverse_hr.db import consume_once
from reverse_hr.domains.candidate import CandidateBase, CandidateProfile, router, subject_lock
from reverse_hr.qualification_contracts import QualificationAdvice


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


def active_decisions(session, candidate):
    latest = {}
    for row in session.scalars(
        select(CandidateDecision).where(CandidateDecision.candidate_id == str(candidate))
    ):
        revision = DecisionSummary.model_validate(row.summary).decision_revision
        if row.session_id not in latest or revision > latest[row.session_id][0]:
            latest[row.session_id] = (revision, row)
    return [value[1] for value in latest.values()]


def current_grade(session, candidate, specialization):
    grades = [
        DecisionSummary.model_validate(row.summary).target_grade
        for row in active_decisions(session, candidate)
        if row.summary["specialization"] == specialization and row.summary["status"] == "confirmed"
    ]
    return max(grades, key=lambda g: list(Grade).index(g)) if grades else None


def grade_binding(session, candidate, specialization):
    grade = current_grade(session, candidate, specialization)
    rows = [
        row
        for row in active_decisions(session, candidate)
        if row.summary["specialization"] == specialization
        and row.summary["status"] == "confirmed"
        and Grade(row.summary["target_grade"]) == grade
    ]
    verified = [row for row in rows if DecisionSummary.model_validate(row.summary).qualification]
    if verified:
        verified.sort(
            key=lambda row: (
                DecisionSummary.model_validate(row.summary).qualification.assessed_at,
                row.decision_id,
            ),
            reverse=True,
        )
        return grade, verified[0].decision_id
    rows.sort(
        key=lambda row: (
            row.received_at.replace(tzinfo=UTC)
            if row.received_at.tzinfo is None
            else row.received_at,
            row.decision_id,
        )
    )
    return grade, rows[0].decision_id if rows else None


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


@router.get("/me/qualification", response_model=list[QualificationAdvice])
def qualification_report(
    request: Request,
    actor: Actor,
    policy_id: UUID | None = None,
    policy_mode: Literal["demo", "production"] = "demo",
):
    actor.require("candidate")
    from reverse_hr.qualification import advice

    if request.app.state.settings.deployment_mode == "production" and policy_mode == "demo":
        raise HTTPException(409, "Demo qualification advice is disabled in production")
    if policy_mode == "production" and policy_id is None:
        raise HTTPException(409, "An approved policy is required for production advice")
    policy = (
        request.app.state.qualification_policy_access.fetch(policy_id, actor.subject, policy_mode)
        if policy_id is not None
        else None
    )
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        results = []
        rows = active_decisions(session, actor.subject)
        summaries = [DecisionSummary.model_validate(row.summary) for row in rows]
        for row, summary in zip(rows, summaries, strict=True):
            if summary.qualification is not None:
                if policy_mode == "production" and summary.qualification.demo:
                    raise HTTPException(
                        409, "Production advice requires production assessment evidence"
                    )
                same = [
                    item.qualification
                    for item in summaries
                    if item.specialization == summary.specialization
                    and item.qualification is not None
                ]
                # A later failed attempt must also constrain advice from older confirmations.
                effective = summary.qualification.model_copy(
                    update={
                        "next_attempt_at": max(item.next_attempt_at for item in same),
                        "grade_change_available_at": max(
                            item.grade_change_available_at for item in same
                        ),
                    }
                )
                summary = summary.model_copy(update={"qualification": effective})
                results.append(
                    advice(
                        UUID(row.decision_id),
                        summary,
                        current_grade(session, actor.subject, summary.specialization),
                        policy=policy,
                    )
                )
        if policy_id is not None:
            # A revocation during report generation closes the response too.
            request.app.state.qualification_policy_access.fetch(
                policy_id, actor.subject, policy_mode
            )
        return sorted(
            results, key=lambda item: (item.assessed_at, str(item.decision_id)), reverse=True
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
                or DecisionSummary.model_validate(existing.summary) != summary
            ):
                raise HTTPException(409)
            return
        profile = session.get(CandidateProfile, str(candidate))
        before = grade_binding(session, candidate, profile.specialization) if profile else None
        for prior in session.scalars(
            select(CandidateDecision).where(
                CandidateDecision.candidate_id == str(candidate),
                CandidateDecision.session_id == str(event.payload["session_id"]),
            )
        ):
            old = DecisionSummary.model_validate(prior.summary)
            if old.decision_revision == summary.decision_revision:
                raise HTTPException(409)
            if (
                summary.decision_revision == 2
                and str(summary.supersedes_decision_id) != prior.decision_id
            ):
                raise HTTPException(409)
            if old.decision_revision == 2 and str(old.supersedes_decision_id) != str(
                event.payload["decision_id"]
            ):
                raise HTTPException(409)
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
        if profile and before != grade_binding(session, candidate, profile.specialization):
            profile.version += 1
            from reverse_hr.domains.candidate_market import emit_profile

            emit_profile(session, profile, event.correlation_id)

    return consume_once(session, "candidate.grade_decision", event, apply)
