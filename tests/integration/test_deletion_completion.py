from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.settings import SERVICES
from reverse_hr.services.privacy.domain.privacy import (
    ConsentRecord,
    ContactGrant,
    DeletionRequest,
    DeletionTarget,
    PrivacySubject,
    process_accepted_invitation,
    process_deletion_ack,
)
from reverse_hr.shared.db import IdempotencyRecord, Inbox, Outbox
from tests.shared.test_access import headers

EXTERNAL = tuple(name for name in SERVICES if name != "privacy")


def prepare(privacy, subject, token):
    auth = token(subject)
    consent = privacy.client.post(
        "/v1/consents",
        headers=headers(auth, "consent"),
        json={"purpose": "contact_disclosure", "document_version": "demo-v1"},
    ).json()
    invitation = uuid4()
    accepted = EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=invitation,
        aggregate_version=1,
        payload={
            "candidate_id": subject,
            "consent_id": UUID(consent["consent_id"]),
            "invitation_id": invitation,
            "organization_id": uuid4(),
        },
    )
    with Session(privacy.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, accepted)
    result = privacy.client.post("/v1/deletion-requests", headers=headers(auth, "delete")).json()
    return result, accepted


def ack(result, producer, *, restricted=False):
    request_id = UUID(result["request_id"])
    return EventEnvelope(
        event_type=f"{producer}.data_{'restricted' if restricted else 'deleted'}.v1",
        producer=producer,
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": UUID(result["candidate_id"]), "request_id": request_id},
    )


def apply(privacy, event):
    with Session(privacy.app.state.engine) as session, session.begin():
        return process_deletion_ack(session, event)


def test_privacy_completes_only_after_all_external_deleted_and_scrubs_own_data(service, token):
    privacy = service("privacy")
    subject, other = uuid4(), uuid4()
    result, accepted = prepare(privacy, subject, token)
    other_consent = privacy.client.post(
        "/v1/consents",
        headers=headers(token(other), "other"),
        json={"purpose": "assessment", "document_version": "demo-v1"},
    ).json()
    for name in EXTERNAL:
        apply(privacy, ack(result, name, restricted=name == "employer"))
    progress = privacy.client.get("/v1/deletion-requests/me", headers=token(subject)).json()
    assert progress["status"] == "in_progress" and progress["completed_at"] is None
    with Session(privacy.app.state.engine) as session:
        assert (
            session.scalar(select(ConsentRecord).where(ConsentRecord.candidate_id == str(subject)))
            is not None
        )
        assert (
            session.scalar(select(ContactGrant).where(ContactGrant.candidate_id == str(subject)))
            is not None
        )
    final = ack(result, "employer")
    assert apply(privacy, final)
    progress = privacy.client.get("/v1/deletion-requests/me", headers=token(subject)).json()
    assert progress["status"] == "completed" and progress["completed_at"] is not None
    assert len(progress["services"]) == len(SERVICES)
    assert all(value == "deleted" for value in progress["services"].values())
    with Session(privacy.app.state.engine) as session:
        assert not list(
            session.scalars(select(ConsentRecord).where(ConsentRecord.candidate_id == str(subject)))
        )
        assert not list(
            session.scalars(select(ContactGrant).where(ContactGrant.candidate_id == str(subject)))
        )
        assert session.get(ConsentRecord, other_consent["consent_id"]).status == "active"
        responses = list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
            )
        )
        assert responses and all(row.operation == "request_deletion" for row in responses)
        assert session.get(PrivacySubject, str(subject)).blocked
        events = [
            row.envelope
            for row in session.scalars(select(Outbox))
            if row.envelope["payload"].get("candidate_id") == str(subject)
        ]
        assert {row["event_type"] for row in events} == {
            "privacy.deletion_requested.v1",
            "privacy.data_deleted.v1",
            "privacy.deletion_completed.v1",
        }
        assert (
            next(row for row in events if row["event_type"] == "privacy.deletion_completed.v1")[
                "aggregate_version"
            ]
            == 2
        )
    # Different IDs and late restricted claims cannot repeat cleanup or undo completion.
    assert not apply(privacy, final)
    assert apply(privacy, final.model_copy(update={"event_id": uuid4()}))
    assert apply(privacy, ack(result, "employer", restricted=True))
    assert privacy.client.get("/v1/deletion-requests/me", headers=token(subject)).json() == progress
    assert (
        privacy.client.post(
            "/v1/consents",
            headers=headers(token(subject), "new"),
            json={"purpose": "assessment", "document_version": "demo-v1"},
        ).status_code
        == 409
    )
    with (
        pytest.raises(HTTPException),
        Session(privacy.app.state.engine) as session,
        session.begin(),
    ):
        process_accepted_invitation(session, accepted.model_copy(update={"event_id": uuid4()}))
    with Session(privacy.app.state.engine) as session:
        completion_events = [
            row
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "privacy.deletion_completed.v1"
        ]
        assert len(completion_events) == 1


def test_final_ack_and_privacy_cleanup_roll_back_together(service, token):
    privacy = service("privacy")
    subject = uuid4()
    result, _ = prepare(privacy, subject, token)
    for name in EXTERNAL[:-1]:
        apply(privacy, ack(result, name))
    final = ack(result, EXTERNAL[-1])
    with pytest.raises(RuntimeError), Session(privacy.app.state.engine) as session, session.begin():
        process_deletion_ack(session, final)
        session.flush()
        raise RuntimeError("abort completion")
    with Session(privacy.app.state.engine) as session:
        assert session.get(DeletionRequest, result["request_id"]).completed_at is None
        assert session.get(DeletionTarget, (result["request_id"], EXTERNAL[-1])).status == "pending"
        assert session.get(Inbox, ("privacy.deletion_ack", str(final.event_id))) is None
        assert (
            session.scalar(select(ConsentRecord).where(ConsentRecord.candidate_id == str(subject)))
            is not None
        )
        assert (
            session.scalar(select(ContactGrant).where(ContactGrant.candidate_id == str(subject)))
            is not None
        )
    assert apply(privacy, final)
    assert (
        privacy.client.get("/v1/deletion-requests/me", headers=token(subject)).json()["status"]
        == "completed"
    )


def test_missing_manifest_and_privacy_self_ack_cannot_complete(service, token):
    privacy = service("privacy")
    result, _ = prepare(privacy, uuid4(), token)
    with pytest.raises(HTTPException):
        apply(privacy, ack(result, "privacy"))
    with Session(privacy.app.state.engine) as session, session.begin():
        target = session.get(DeletionTarget, (result["request_id"], "notification"))
        session.delete(target)
    for name in EXTERNAL:
        if name != "notification":
            apply(privacy, ack(result, name))
    with Session(privacy.app.state.engine) as session:
        assert session.get(DeletionRequest, result["request_id"]).completed_at is None
        assert session.scalar(select(ConsentRecord)) is not None
