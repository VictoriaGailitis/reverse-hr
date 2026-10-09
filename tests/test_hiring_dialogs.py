"""Dialogs and in-app notices across migrated DBs with real signed service RPC."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture
from test_matching_hiring import consent, invite
from test_matching_hiring import setup as market_setup

from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.hiring import process_deletion_request as erase_hiring
from reverse_hr.domains.hiring_dialogs import Complaint, Dialog, EmployerBlock, Message, Notice
from reverse_hr.domains.notification import NotificationRow, process_notice
from reverse_hr.domains.notification import process_deletion_request as erase_notification
from reverse_hr.domains.privacy import process_accepted_invitation
from reverse_hr.event_transport import NotificationConsumer
from reverse_hr.events import EventEnvelope
from reverse_hr.market_access import MarketAccess, context
from reverse_hr.market_contracts import MarketRequest
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import ProcessingAccess, sign

signatures = signatures_fixture
setup = market_setup


@pytest.fixture
def flow(setup, service):
    s = setup
    s.notification = service("notification")
    target = s.notification
    target.app.state.notification_signatures = s.signatures["notification"]
    processing = ProcessingAccess(target.app.state.settings)
    processing._signatures, processing._send = s.signatures["notification"], s.sender
    target.app.state.processing_access = processing
    access = MarketAccess(target.app.state.settings)
    access._signatures, access._send = s.signatures["notification"], s.sender
    target.app.state.market_access = access
    s.iid = invite(s).json()["invitation_id"]
    s.disclosure = consent(s, "contact_disclosure")
    accepted = s.hiring.client.post(
        f"/v1/invitations/{s.iid}/accept",
        json={"disclosure_consent_id": s.disclosure},
        headers=headers(s.auth, "accept", 1),
    )
    assert accepted.status_code == 200, accepted.text
    s.path = f"/v1/dialogs/{s.iid}"
    return s


def events(s, kind):
    with Session(s.hiring.app.state.engine) as session:
        return [
            EventEnvelope.model_validate(row.envelope)
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "hiring." + kind + ".v1"
        ]


def deliver_grant(s):
    with Session(s.privacy.app.state.engine) as session, session.begin():
        process_accepted_invitation(session, events(s, "invitation_accepted")[0])


def deliver_notices(s):
    with Session(s.notification.app.state.engine) as session, session.begin():
        for event in events(s, "notification_requested"):
            process_notice(session, event, s.notification.app.state.market_access)


def send(s, key="msg", version=1, auth=None, text="Hello, can we discuss the role?"):
    return s.hiring.client.post(
        s.path + "/messages", json={"text": text}, headers=headers(auth or s.auth, key, version)
    )


def test_acceptance_opens_one_dialog_then_grant_opens_messages(flow):
    s = flow
    again = s.hiring.client.post(
        f"/v1/invitations/{s.iid}/accept",
        json={"disclosure_consent_id": s.disclosure},
        headers=headers(s.auth, "accept", 1),
    )
    assert again.status_code == 200
    with Session(s.hiring.app.state.engine) as session:
        assert len(list(session.scalars(select(Dialog)))) == 1
        assert len(list(session.scalars(select(Notice)))) == 2
    assert s.hiring.client.get(s.path, headers=s.auth).json()["last_sequence"] == 0
    assert send(s).status_code == 409
    deliver_grant(s)
    sent = send(s)
    assert sent.status_code == 201, sent.text
    assert send(s).json() == sent.json()
    assert send(s, text="Different content").status_code == 409
    assert send(s, key="stale").status_code == 409
    reply = send(s, "reply", 2, s.employer_auth, "Available tomorrow")
    assert reply.status_code == 201, reply.text
    rows = s.hiring.client.get(s.path + "/messages", headers=s.auth).json()
    assert [m["sequence"] for m in rows] == [1, 2]
    assert s.hiring.client.get(s.path + "/messages?after=1", headers=s.employer_auth).json() == [
        reply.json()
    ]
    with Session(s.hiring.app.state.engine) as session:
        cached = list(session.scalars(select(IdempotencyRecord)))
        assert not any(
            "Hello, can" in row.response or "Available tomorrow" in row.response for row in cached
        )
        notices = events(s, "notification_requested")
        assert len(notices) == 4
        assert all(
            set(e.payload)
            == {
                "notice_id",
                "recipient_id",
                "invitation_id",
                "candidate_id",
                "organization_id",
                "actor_id",
                "creator_id",
            }
            for e in notices
        )


def test_notice_delivery_duplicate_natural_key_preferences_and_read(flow):
    s = flow
    deliver_grant(s)
    assert send(s).status_code == 201
    deliver_notices(s)
    deliver_notices(s)
    event = events(s, "notification_requested")[-1]
    with Session(s.notification.app.state.engine) as session, session.begin():
        assert process_notice(
            session,
            event.model_copy(update={"event_id": uuid4()}),
            s.notification.app.state.market_access,
        )
        assert len(list(session.scalars(select(NotificationRow)))) == 3
    candidate_rows = s.notification.client.get("/v1/notifications", headers=s.auth).json()
    recruiter_rows = s.notification.client.get("/v1/notifications", headers=s.employer_auth).json()
    assert len(candidate_rows) == 1 and len(recruiter_rows) == 2
    assert all(
        set(r) == {"notice_id", "invitation_id", "kind", "read", "version"} for r in recruiter_rows
    )
    assert {r["kind"] for r in recruiter_rows} == {"invitation_accepted", "dialog_message"}
    notice_id = recruiter_rows[0]["notice_id"]
    path = f"/v1/notifications/{notice_id}/read"
    assert (
        s.notification.client.post(path, headers=headers(s.auth, "foreign", 1)).status_code == 404
    )
    marked = s.notification.client.post(path, headers=headers(s.employer_auth, "read", 1))
    assert marked.status_code == 200 and marked.json()["read"]
    assert (
        s.notification.client.post(path, headers=headers(s.employer_auth, "read", 1)).json()
        == marked.json()
    )
    disabled = s.notification.client.put(
        "/v1/notifications/preferences",
        json={"in_app": False},
        headers=headers(s.employer_auth, "disable", 1),
    )
    assert disabled.status_code == 200 and disabled.json()["version"] == 2
    assert s.notification.client.get("/v1/notifications", headers=s.employer_auth).json() == []
    assert (
        s.notification.client.put(
            "/v1/notifications/preferences",
            json={"in_app": True},
            headers=headers(s.employer_auth, "enable", 2),
        ).status_code
        == 200
    )
    assert len(s.notification.client.get("/v1/notifications", headers=s.employer_auth).json()) == 2


def test_withdrawn_consent_blocks_read_send_and_idempotent_reply(flow):
    s = flow
    deliver_grant(s)
    assert send(s).status_code == 201
    assert (
        s.privacy.client.post(
            f"/v1/consents/{s.disclosure}/revoke", headers=headers(s.auth, "revoke", 1)
        ).status_code
        == 200
    )
    assert s.hiring.client.get(s.path + "/messages", headers=s.employer_auth).status_code == 409
    assert send(s).status_code == 409
    assert send(s, "later", 2, s.employer_auth).status_code == 409


def test_block_closes_company_messages_contacts_new_invitations_and_notices(flow):
    s = flow
    deliver_grant(s)
    assert send(s).status_code == 201
    deliver_notices(s)
    blockpath = s.path + "/block"
    assert (
        s.hiring.client.post(blockpath, headers=headers(s.employer_auth, "bad", 2)).status_code
        == 403
    )
    result = s.hiring.client.post(blockpath, headers=headers(s.auth, "block", 2))
    assert result.status_code == 200 and result.json()["blocked"]
    assert (
        s.hiring.client.post(blockpath, headers=headers(s.auth, "block", 2)).json() == result.json()
    )
    assert send(s).status_code == 409
    assert s.hiring.client.get(s.path + "/messages", headers=s.employer_auth).status_code == 409
    assert (
        s.hiring.client.get(
            f"/v1/invitations/{s.iid}/contacts", headers=s.employer_auth
        ).status_code
        == 409
    )
    assert invite(s, "new-after-block").status_code == 409
    assert s.notification.client.get("/v1/notifications", headers=s.employer_auth).json() == []
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []


def test_complaint_after_block_is_private_and_checks_exact_message(flow):
    s = flow
    deliver_grant(s)
    message = send(s).json()
    assert (
        s.hiring.client.post(s.path + "/block", headers=headers(s.auth, "block", 2)).status_code
        == 200
    )
    data = {"message_id": message["message_id"], "reason": "Please review this communication"}
    complaint = s.hiring.client.post(
        s.path + "/complaints", json=data, headers=headers(s.auth, "complaint")
    )
    assert complaint.status_code == 201, complaint.text
    assert (
        s.hiring.client.post(
            s.path + "/complaints", json=data, headers=headers(s.auth, "complaint")
        ).json()
        == complaint.json()
    )
    assert (
        s.hiring.client.post(
            s.path + "/complaints",
            json=data | {"message_id": str(uuid4())},
            headers=headers(s.auth, "unknown"),
        ).status_code
        == 404
    )
    assert s.hiring.client.post(
        s.path + "/complaints", json=data, headers=headers(s.token(uuid4()), "outsider")
    ).status_code in {403, 404}
    with Session(s.hiring.app.state.engine) as session:
        assert len(list(session.scalars(select(Complaint)))) == 1
        cache = list(session.scalars(select(IdempotencyRecord)))
        assert not any(data["reason"] in row.response for row in cache)
    assert len(events(s, "complaint_created")) == 1


def test_membership_and_source_unavailability_never_serve_cached_text(flow):
    s = flow
    deliver_grant(s)
    assert send(s).status_code == 201
    old = s.hiring.app.state.market_access._send

    def unavailable(*args, **kwargs):
        raise HTTPException(503)

    s.hiring.app.state.market_access._send = unavailable
    assert send(s).status_code == 503
    assert s.hiring.client.get(s.path + "/messages", headers=s.auth).status_code == 503
    s.hiring.app.state.market_access._send = old
    outsider = s.token(uuid4(), ("employer",))
    assert s.hiring.client.get(s.path + "/messages", headers=outsider).status_code == 409
    assert s.notification.client.get("/v1/notifications", headers=outsider).json() == []


def test_erasure_cleans_dialogs_notices_caches_and_late_events_cannot_restore(flow):
    s = flow
    deliver_grant(s)
    assert send(s).status_code == 201
    deliver_notices(s)
    old_events = events(s, "notification_requested")
    event = deletion(s.candidate_id)
    # Notification receives deletion before Hiring; even a still-allowed source cannot resurrect it.
    with Session(s.notification.app.state.engine) as session, session.begin():
        assert erase_notification(session, event)
        for notice_event in old_events:
            process_notice(
                session,
                notice_event.model_copy(update={"event_id": uuid4()}),
                s.notification.app.state.market_access,
            )
        assert session.scalar(select(NotificationRow)) is None
    with Session(s.hiring.app.state.engine) as session, session.begin():
        assert erase_hiring(session, event)
        assert not erase_hiring(session, event)
        for model in (Dialog, Message, Complaint, Notice, EmployerBlock):
            assert session.scalar(select(model)) is None
        assert (
            session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.operation.like("message:%"))
            )
            is None
        )
    assert s.notification.client.get("/v1/notifications", headers=s.employer_auth).json() == []
    assert s.hiring.client.get(s.path, headers=s.employer_auth).status_code == 404
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.notification.app.state.settings), "base")
    assert s.notification.client.get("/health/ready").status_code == 200


def test_private_notice_export_signature_recipient_and_nonce(flow):
    s = flow
    event = events(s, "notification_requested")[0]
    body = MarketRequest(
        requester="notification",
        purpose="notice",
        issued_at=datetime.now(UTC),
        nonce=uuid4(),
        candidate_id=s.candidate_id,
        notice_id=event.aggregate_id,
    )
    signed = sign(s.signatures["notification"], context("hiring", "notice", "request"), body)

    def post(request_body, signature):
        return s.hiring.client.post(
            "/internal/v1/market/notice",
            json=request_body.model_dump(mode="json"),
            headers={"X-HR-Signature": signature},
        )

    assert post(body, "invalid").status_code == 401
    assert post(body, signed).json()["allowed"]
    assert post(body, signed).status_code == 401
    wrong = body.model_copy(update={"candidate_id": uuid4(), "nonce": uuid4()})
    assert not post(
        wrong, sign(s.signatures["notification"], context("hiring", "notice", "request"), wrong)
    ).json()["allowed"]
    assert (
        post(
            body.model_copy(update={"issued_at": datetime.now(UTC) - timedelta(minutes=1)}), signed
        ).status_code
        == 401
    )


def test_signed_consumer_commit_ack_retry_and_forgery(flow):
    s = flow
    event = events(s, "notification_requested")[0]
    consumer = NotificationConsumer(
        s.notification.app.state.engine,
        s.signatures["notification"],
        s.notification.app.state.settings,
    )
    consumer.access._send = s.sender
    raw, signed = s.signatures["hiring"].sign(event)
    method = SimpleNamespace(exchange="events.hiring", delivery_tag=17)
    properties = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    channel = Mock()

    def committed(**kwargs):
        with Session(s.notification.app.state.engine) as session:
            assert session.get(NotificationRow, str(event.aggregate_id)) is not None

    channel.basic_ack.side_effect = committed
    consumer(channel, method, properties, raw)
    channel.basic_ack.assert_called_once()
    invalid = Mock()
    consumer(invalid, method, properties, raw + b"x")
    assert invalid.basic_publish.call_args.kwargs["exchange"] == "dead.notification"
    assert "Please" not in str(invalid.basic_publish.call_args)
    retry = Mock()

    def unavailable(*args, **kwargs):
        raise HTTPException(503)

    consumer.access._send = unavailable
    consumer(retry, method, properties, raw)
    assert retry.basic_publish.call_args.kwargs["exchange"] == "retry.notification"


@pytest.mark.parametrize("name", ["hiring", "notification"])
def test_empty_domain_migration_round_trip(service, name):
    target = service(name)
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "base")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200


def test_hiring_upgrade_backfills_preexisting_accepted_dialog_without_fake_notices(flow):
    from reverse_hr.domains.hiring import InvitationRevision

    s = flow
    config = migration_config(s.hiring.app.state.settings)
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.query(Dialog).delete()
        session.query(Notice).delete()
    with pytest.raises(RuntimeError, match="populated"):
        command.downgrade(config, "0002_hiring")
    assert s.hiring.client.get("/health/ready").status_code == 200
    # Explicitly construct pre-history data for this legacy upgrade fixture.
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.query(InvitationRevision).delete()
    command.downgrade(config, "0002_hiring")
    command.upgrade(config, "head")
    with Session(s.hiring.app.state.engine) as session:
        assert session.get(Dialog, s.iid).version == 1
        assert session.scalar(select(Notice)) is None


def test_candidate_erasure_removes_other_actors_reply_and_read_command_caches(flow):
    s = flow
    deliver_grant(s)
    response = send(s, auth=s.employer_auth)
    assert response.status_code == 201
    deliver_notices(s)
    notices = s.notification.client.get("/v1/notifications", headers=s.employer_auth).json()
    result = s.notification.client.post(
        f"/v1/notifications/{notices[0]['notice_id']}/read",
        headers=headers(s.employer_auth, "read", 1),
    )
    assert result.status_code == 200
    event = deletion(s.candidate_id)
    for target, handler in ((s.hiring, erase_hiring), (s.notification, erase_notification)):
        with Session(target.app.state.engine) as session, session.begin():
            handler(session, event)
            assert (
                session.scalar(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.operation.like("message:%")
                        | IdempotencyRecord.operation.like("notice_read:%")
                    )
                )
                is None
            )
    with Session(s.hiring.app.state.engine) as session:
        assert events(s, "notification_requested") == []
        assert session.scalar(select(Message)) is None


def test_revoked_recruiter_cannot_read_or_replay_own_message(flow):
    s = flow
    subject = uuid4()
    auth = s.token(subject, ("employer",))
    created = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json={"subject": str(subject), "role": "recruiter"},
        headers=headers(s.employer_auth, "member", 2),
    )
    assert created.status_code == 201, created.text
    deliver_grant(s)
    assert send(s, auth=auth).status_code == 201
    membership = created.json()["membership_id"]
    revoked = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members/{membership}/revoke",
        headers=headers(s.employer_auth, "remove", 1),
    )
    assert revoked.status_code == 200, revoked.text
    assert send(s, auth=auth).status_code == 409
    assert s.hiring.client.get(s.path + "/messages", headers=auth).status_code == 409


@pytest.mark.parametrize(
    "mutation", ["future", "wrong_recipient", "wrong_invitation", "extra_payload"]
)
def test_notification_rejects_stale_bindings_and_invalid_events(flow, mutation):
    s = flow
    event = events(s, "notification_requested")[0]
    if mutation == "future":
        event = event.model_copy(update={"occurred_at": datetime.now(UTC) + timedelta(minutes=3)})
    else:
        key = {
            "wrong_recipient": "recipient_id",
            "wrong_invitation": "invitation_id",
            "extra_payload": "unexpected_id",
        }[mutation]
        event = event.model_copy(update={"payload": event.payload | {key: uuid4()}})
    with Session(s.notification.app.state.engine) as session:
        if mutation == "wrong_recipient":
            # A denied recipient can be acknowledged without creating a notice.
            with session.begin():
                process_notice(session, event, s.notification.app.state.market_access)
            assert session.scalar(select(NotificationRow)) is None
        else:
            with pytest.raises(HTTPException):
                with session.begin():
                    process_notice(session, event, s.notification.app.state.market_access)
            assert session.scalar(select(NotificationRow)) is None


def test_creator_erasure_purges_notices_from_another_employee_and_late_delivery(flow):
    s = flow
    subject = uuid4()
    auth = s.token(subject, ("employer",))
    created = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json={"subject": str(subject), "role": "recruiter"},
        headers=headers(s.employer_auth, "member", 2),
    )
    assert created.status_code == 201, created.text
    deliver_grant(s)
    assert send(s, auth=auth).status_code == 201
    deliver_notices(s)
    late = events(s, "notification_requested")[-1].model_copy(update={"event_id": uuid4()})
    event = deletion(s.recruiter_id)
    with Session(s.notification.app.state.engine) as session, session.begin():
        erase_notification(session, event)
        assert process_notice(session, late, s.notification.app.state.market_access)
        assert session.scalar(select(NotificationRow)) is None
    with Session(s.hiring.app.state.engine) as session, session.begin():
        erase_hiring(session, event)
        assert session.scalar(select(Message)) is None
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []


def test_employee_erasure_removes_complaint_derived_from_message_but_preserves_dialog(flow):
    s = flow
    subject = uuid4()
    auth = s.token(subject, ("employer",))
    created = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json={"subject": str(subject), "role": "recruiter"},
        headers=headers(s.employer_auth, "member", 2),
    )
    assert created.status_code == 201
    deliver_grant(s)
    message = send(s, auth=auth).json()
    complaint = s.hiring.client.post(
        s.path + "/complaints",
        json={"message_id": message["message_id"], "reason": "A quote from the employee's message"},
        headers=headers(s.auth, "complaint"),
    )
    assert complaint.status_code == 201
    with Session(s.hiring.app.state.engine) as session, session.begin():
        erase_hiring(session, deletion(subject))
        assert session.get(Dialog, s.iid) is not None
        assert session.scalar(select(Message)) is None
        assert session.scalar(select(Complaint)) is None
        assert (
            session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.operation.like("complaint:%"))
            )
            is None
        )
    assert events(s, "complaint_created") == []
    assert s.hiring.client.get(s.path + "/messages", headers=s.auth).json() == []
