from datetime import UTC, datetime, timedelta
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import JSON, DateTime, String, delete, select, update
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.contracts.core import Profile, ProfileUpdate
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord, consume_once, enqueue


class CandidateBase(DeclarativeBase):
    pass


class CandidateProfile(CandidateBase):
    __tablename__ = "candidate_profiles"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(100))
    specialization: Mapped[str] = mapped_column(String(100))
    declared_grade: Mapped[str] = mapped_column(String(16))
    additional_specializations: Mapped[list] = mapped_column(
        JSON, default=list, server_default="[]"
    )
    version: Mapped[int]


router = APIRouter(prefix="/v1/candidates", tags=["candidate"])


def view(row, session):
    from reverse_hr.services.candidate.domain.candidate_grades import current_grade

    return Profile(
        candidate_id=row.candidate_id,
        display_name=row.display_name,
        specialization=row.specialization,
        declared_grade=row.declared_grade,
        confirmed_grade=current_grade(session, row.candidate_id, row.specialization),
        additional_specializations=row.additional_specializations or [],
        specializations=[
            dict(
                **item,
                confirmed_grade=current_grade(session, row.candidate_id, item["specialization"]),
            )
            for item in specialization_choices(row)
        ],
        version=row.version,
    ).model_dump(mode="json")


def specialization_choices(row):
    return [
        dict(specialization=row.specialization, declared_grade=row.declared_grade),
        *(row.additional_specializations or []),
    ]


@router.get("/me", response_model=Profile)
def get_profile(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        profile = session.get(CandidateProfile, str(actor.subject))
        if profile is None:
            raise HTTPException(404)
        return view(profile, session)


@router.post("/me", response_model=Profile, status_code=201)
def create_profile(request: Request, actor: Actor, body: ProfileUpdate, idempotency: CommandKey):
    actor.require("candidate")

    def change(session):
        row = CandidateProfile(
            candidate_id=str(actor.subject), **body.model_dump(mode="json"), version=1
        )
        session.add(row)
        session.flush()
        enqueue(
            session,
            EventEnvelope(
                event_type="candidate.profile_created.v1",
                producer="candidate",
                correlation_id=request.state.trace_id,
                aggregate_id=actor.subject,
                aggregate_version=1,
                payload={"candidate_id": actor.subject},
            ),
        )
        return view(row, session)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_profile",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@router.put("/me", response_model=Profile)
def update_profile(
    request: Request,
    actor: Actor,
    body: ProfileUpdate,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")
    version = int(if_match.strip('"'))

    def change(session):
        changes = body.model_dump(mode="json", exclude_unset=True)
        if "additional_specializations" not in body.model_fields_set:
            current = session.get(CandidateProfile, str(actor.subject))
            if current is not None:
                changes["additional_specializations"] = [
                    item
                    for item in (current.additional_specializations or [])
                    if item["specialization"].casefold() != body.specialization.casefold()
                ]
        result = session.execute(
            update(CandidateProfile)
            .where(
                CandidateProfile.candidate_id == str(actor.subject),
                CandidateProfile.version == version,
            )
            .values(**changes, version=version + 1)
        )
        if result.rowcount != 1:
            exists = session.scalar(
                select(CandidateProfile.candidate_id).where(
                    CandidateProfile.candidate_id == str(actor.subject)
                )
            )
            raise HTTPException(409 if exists else 404)
        row = session.get(CandidateProfile, str(actor.subject))
        enqueue(
            session,
            EventEnvelope(
                event_type="candidate.profile_updated.v1",
                producer="candidate",
                correlation_id=request.state.trace_id,
                aggregate_id=UUID(row.candidate_id),
                aggregate_version=row.version,
                payload={"candidate_id": actor.subject},
            ),
        )
        return view(row, session)

    return execute(
        request.app.state.engine,
        actor.subject,
        "update_profile",
        idempotency,
        {"body": body.model_dump(mode="json"), "version": version},
        change,
        guard=lambda session: subject_lock(session, actor.subject),
    )


class CandidateSubject(CandidateBase):
    __tablename__ = "candidate_subjects"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    deletion_request_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


def subject_lock(session, candidate_id, *, allow_blocked=False):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(CandidateSubject)
        .values(candidate_id=str(candidate_id), blocked=False)
        .on_conflict_do_nothing(index_elements=["candidate_id"])
    )
    row = session.scalar(
        select(CandidateSubject)
        .where(CandidateSubject.candidate_id == str(candidate_id))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.blocked and not allow_blocked:
        raise HTTPException(409)
    return row


def process_deletion_request(session, event):
    """Transport must authenticate Privacy. All local effects share its transaction."""
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = event.payload["candidate_id"]
        request_id = str(event.payload["request_id"])
        row = subject_lock(session, subject, allow_blocked=True)
        if row.deletion_request_id is not None and row.deletion_request_id != request_id:
            raise HTTPException(409)
        # Repeat the scrub even after inbox replay is assigned a new event ID.
        # Reusing the same request with a new event ID never creates another ACK.
        from reverse_hr.services.candidate.domain.candidate_grades import CandidateDecision
        from reverse_hr.services.candidate.domain.candidate_preferences import PreferenceRow
        from reverse_hr.services.candidate.domain.candidate_resume import purge

        session.execute(delete(PreferenceRow).where(PreferenceRow.candidate_id == str(subject)))
        from reverse_hr.services.candidate.domain.candidate_recommendations import (
            TaskRecommendation,
            TaskSubscription,
        )

        for model in (TaskSubscription, TaskRecommendation):
            session.execute(delete(model).where(model.candidate_id == str(subject)))
        purge(session, subject)
        session.execute(
            delete(CandidateDecision).where(CandidateDecision.candidate_id == str(subject))
        )
        session.execute(
            delete(CandidateProfile).where(CandidateProfile.candidate_id == str(subject))
        )
        from reverse_hr.services.candidate.domain.candidate_market import Contacts, Publication

        session.execute(delete(Publication).where(Publication.candidate_id == str(subject)))
        session.execute(delete(Contacts).where(Contacts.candidate_id == str(subject)))
        session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject)))
        from reverse_hr.shared.db import Outbox

        for notice_event in session.scalars(select(Outbox)).all():
            if notice_event.envelope.get(
                "event_type"
            ) == "candidate.task_notification_requested.v1" and notice_event.envelope.get(
                "payload", {}
            ).get("recipient_id") == str(subject):
                session.delete(notice_event)
        first = row.deletion_request_id is None
        row.blocked = True
        row.deletion_request_id = request_id
        row.deleted_at = datetime.now(UTC)
        if first:
            enqueue(
                session,
                EventEnvelope(
                    event_type="candidate.data_deleted.v1",
                    producer="candidate",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    aggregate_version=1,
                    payload=event.payload,
                ),
            )

    return consume_once(session, "candidate.deletion_request", event, apply)
