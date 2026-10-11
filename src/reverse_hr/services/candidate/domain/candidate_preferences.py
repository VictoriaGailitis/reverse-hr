"""Candidate-owned, explicitly confirmed employment preferences and selective publication."""

from datetime import UTC, datetime
from typing import Annotated

from fastapi import Header, HTTPException, Request
from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.matching_conditions import (
    CandidatePreferenceCommand,
    CandidatePreferences,
)
from reverse_hr.services.candidate.domain.candidate import (
    CandidateBase,
    CandidateProfile,
    router,
    subject_lock,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, execute

PreferenceVersion = Annotated[str, Header(alias="If-Match", pattern=r'^"[0-9]+"$')]


class PreferenceRow(CandidateBase):
    __tablename__ = "candidate_preferences"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    document: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int]
    confirmed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    share_in_matching: Mapped[bool]


def preference_view(row):
    timestamp = row.confirmed_at
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    return CandidatePreferences(**row.document, version=row.version, confirmed_at=timestamp)


def public_preferences(session, candidate_id):
    row = session.get(PreferenceRow, str(candidate_id))
    return preference_view(row) if row is not None and row.share_in_matching else None


def apply_preferences_correction(
    session, subject, values, expected_version, correlation_id, expected_profile_version=None
):
    """Shared by direct candidate updates and signed Privacy CAS correction commands."""
    body = CandidatePreferenceCommand.model_validate(values)
    subject_lock(session, subject)
    profile = session.get(CandidateProfile, str(subject))
    if profile is None:
        raise HTTPException(404)
    if expected_profile_version is not None and profile.version != expected_profile_version:
        raise HTTPException(409, "Profile changed; read current correction source")
    row = session.get(PreferenceRow, str(subject))
    if expected_version != (row.version if row else 0):
        raise HTTPException(409, "Preferences changed; read the current version")
    if row is None:
        row = PreferenceRow(candidate_id=str(subject), version=0)
        session.add(row)
    row.document = body.model_dump(mode="json", exclude={"share_in_matching", "confirmed"})
    row.version += 1
    row.confirmed_at = datetime.now(UTC)
    row.share_in_matching = body.share_in_matching
    profile.version += 1
    from reverse_hr.services.candidate.domain.candidate_market import emit_profile

    emit_profile(session, profile, correlation_id)
    session.flush()
    return {
        **preference_view(row).model_dump(mode="json"),
        "share_in_matching": row.share_in_matching,
    }


@router.get("/me/preferences")
def get_preferences(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(PreferenceRow, str(actor.subject))
        if row is None:
            return {"version": 0, "preferences": None, "share_in_matching": False}
        request.app.state.processing_access.check(actor.subject)
        return {
            "version": row.version,
            "preferences": preference_view(row).model_dump(mode="json"),
            "share_in_matching": row.share_in_matching,
        }


@router.put("/me/preferences")
def update_preferences(
    request: Request,
    actor: Actor,
    body: CandidatePreferenceCommand,
    idempotency: CommandKey,
    if_match: PreferenceVersion,
):
    actor.require("candidate")
    expected = int(if_match.strip('"'))

    def guard(session):
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)

    def change(session):
        return apply_preferences_correction(
            session, actor.subject, body.model_dump(mode="json"), expected, request.state.trace_id
        )

    def present(session, result):
        # Return current state, not cached declarations after a later withdrawal/correction.
        row = session.get(PreferenceRow, str(actor.subject))
        if row is None:
            raise HTTPException(404)
        request.app.state.processing_access.check(actor.subject)
        return {
            **preference_view(row).model_dump(mode="json"),
            "share_in_matching": row.share_in_matching,
        }

    return execute(
        request.app.state.engine,
        actor.subject,
        "candidate_preferences",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": expected},
        change,
        200,
        guard=guard,
        present=present,
    )
