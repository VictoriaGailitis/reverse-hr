"""Fresh, minimal external ATS status beside the human-owned hiring workflow."""

from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import JSON, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.protocols.market_state import lock
from reverse_hr.services.hiring.domain.hiring import (
    HiringBase,
    HiringSubject,
    InvitationRow,
    invitation_guard,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.db import Inbox, consume_once


class ATSProjection(HiringBase):
    __tablename__ = "hiring_ats_statuses"
    job_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    organization_id: Mapped[str] = mapped_column(String(36), index=True)
    invitation_id: Mapped[str] = mapped_column(String(36), index=True)
    actor_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int]
    data: Mapped[dict] = mapped_column(JSON)


router = APIRouter(prefix="/v1/invitations", tags=["hiring-ats"])


def outcome(access, candidate, key):
    try:
        data = access.call("integration", "outcome", UUID(str(candidate)), UUID(str(key)))
    except HTTPException as exc:
        if exc.status_code in {401, 403, 404, 409}:
            return None
        raise
    expected = {
        "job_id",
        "candidate_id",
        "organization_id",
        "invitation_id",
        "actor_id",
        "external_id",
        "status",
        "sequence",
        "revision",
        "demo",
    }
    if (
        set(data) != expected
        or data["job_id"] != str(key)
        or data["candidate_id"] != str(candidate)
        or type(data["sequence"]) is not int
        or data["sequence"] < 1
        or type(data["revision"]) is not int
        or data["status"] not in {"received", "interview", "offer", "hired", "rejected"}
        or data["demo"] is not True
    ):
        raise HTTPException(503)
    for field in ("actor_id", "organization_id", "invitation_id", "external_id"):
        UUID(data[field])
    return data


def process_status(session, event, access):
    if (
        event.producer != "integration"
        or event.event_type != "integration.ats_status_changed.v1"
        or set(event.payload) != {"candidate_id", "organization_id", "job_id"}
        or event.aggregate_id != event.payload["job_id"]
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)
    if session.get(Inbox, ("hiring.ats_status", str(event.event_id))):
        return False
    data = outcome(access, event.payload["candidate_id"], event.payload["job_id"])
    if data and (
        data["organization_id"] != str(event.payload["organization_id"])
        or data["revision"] < event.aggregate_version
    ):
        raise HTTPException(409)

    def apply(session, event):
        candidate, key = str(event.payload["candidate_id"]), str(event.payload["job_id"])
        subjects = {candidate} | ({data["actor_id"]} if data else set())
        states = [
            lock(session, HiringSubject, subject, allow_blocked=True)
            for subject in sorted(subjects)
        ]
        row = session.get(ATSProjection, key)
        if data is None or any(item.blocked for item in states):
            if row:
                session.delete(row)
            return
        invitation = session.get(InvitationRow, data["invitation_id"])
        if (
            invitation is None
            or invitation.candidate_id != candidate
            or invitation.organization_id != data["organization_id"]
            or invitation.status != "accepted"
        ):
            raise HTTPException(409)
        if row and row.revision > data["revision"]:
            return
        if row and row.revision == data["revision"] and row.data != data:
            raise HTTPException(409)
        if row is None:
            row = ATSProjection(
                job_id=key,
                candidate_id=candidate,
                organization_id=data["organization_id"],
                invitation_id=data["invitation_id"],
                actor_id=data["actor_id"],
            )
            session.add(row)
        row.revision, row.data = data["revision"], data

    return consume_once(session, "hiring.ats_status", event, apply)


@router.get("/{invitation_id}/ats-status")
def get_status(request: Request, actor: Actor, invitation_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        invitation = invitation_guard(request, actor, invitation_id, session)
        rows = list(
            session.scalars(
                select(ATSProjection)
                .where(ATSProjection.invitation_id == str(invitation_id))
                .order_by(ATSProjection.revision.desc())
                .limit(50)
            )
        )
        candidate = invitation.candidate_id
        job_ids = [row.job_id for row in rows]
    # No Hiring fence spans an Integration request (which checks Hiring permission).
    current = [outcome(request.app.state.exchange_access, candidate, key) for key in job_ids]
    with Session(request.app.state.engine) as session, session.begin():
        invitation_guard(request, actor, invitation_id, session)
        return [
            dict(
                job_id=row["job_id"],
                external_id=row["external_id"],
                status=row["status"],
                sequence=row["sequence"],
                demo=row["demo"],
            )
            for row in current
            if row is not None
        ]


def scrub(session, subject):
    session.execute(
        delete(ATSProjection).where(
            (ATSProjection.candidate_id == subject) | (ATSProjection.actor_id == subject)
        )
    )
