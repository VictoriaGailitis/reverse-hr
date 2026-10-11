"""Real service DBs/signed RPC: schedules, permission epochs, retry and notification scopes."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.market_access import MarketAccess
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.services.assessment.company_dispatch import run_one
from reverse_hr.services.assessment.domain.assessment_sessions import process_deletion_request
from reverse_hr.services.assessment.domain.company_assignments import CompanyAssignment
from reverse_hr.services.assessment.domain.company_schedules import (
    CompanyJob,
    CompanyNoticeSource,
    CompanySchedule,
    CompanySubscription,
)
from reverse_hr.services.notification.consumer import NotificationConsumer
from reverse_hr.services.notification.domain.notification import (
    NotificationRow,
    process_company_notice,
)
from reverse_hr.services.notification.domain.notification import (
    process_deletion_request as delete_notifications,
)
from reverse_hr.shared.db import Outbox
from tests.integration.test_matching_hiring import consent
from tests.integration.test_matching_hiring import setup as market_setup
from tests.services.assessment.test_company_assignments import accept, confirm, grant
from tests.services.assessment.test_company_assignments import completed as completed_fixture
from tests.services.assessment.test_company_tasks import company as company_fixture
from tests.services.assessment.test_company_tasks import create, package, review, submit
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

company = company_fixture
setup = market_setup
signatures = signatures_fixture
completed = completed_fixture


def subscribe(s, status="active", version=1, key="subscribe", **extra):
    if status == "active" and not hasattr(s, "subscription_consent"):
        s.subscription_consent = consent(s, "company_task_subscription")
    body = dict(status=status, min_interval_seconds=86400)
    if status == "active":
        body["consent_id"] = s.subscription_consent
    body.update(extra)
    return s.assessment.client.put(
        "/v1/company-task-subscriptions/" + s.organization_id,
        headers=headers(s.auth, key, version),
        json=body,
    )


def approved(s):
    proposal = create(s, content=package("code", "artifact")).json()
    s.proposal = review(s, submit(s, proposal).json()).json()
    reply = s.assessment.client.post(
        "/v1/assessment-plans",
        headers=headers(s.reviewer, "plan"),
        json=dict(
            name="Scheduled task",
            revision_ids=[s.proposal["revision_id"]],
            reason="Independent publication",
        ),
    )
    assert reply.status_code == 201, reply.text
    s.plan = reply.json()


def schedule(s, key="schedule", **extra):
    body = (
        dict(
            organization_id=s.organization_id,
            candidate_id=str(s.candidate_id),
            proposal_id=s.proposal["proposal_id"],
            plan_version_id=s.plan["plan_version_id"],
            starts_at=datetime.now(UTC).isoformat(),
        )
        | extra
    )
    return s.assessment.client.post(
        "/v1/company-task-schedules", headers=headers(s.employer_auth, key), json=body
    )


def tick(s, now=None):
    return run_one(
        s.assessment.app.state.engine,
        s.assessment.app.state.processing_access,
        s.assessment.app.state.market_access,
        s.assessment.app.state.grade_access,
        now=now,
    )


def rows(s, model):
    with Session((s.assessment if hasattr(s, "assessment") else s).app.state.engine) as db:
        return list(db.scalars(select(model)))


def notification(s, service):
    s.notification = service("notification")
    original = s.sender
    s.assessment.app.state.assessment_signatures = s.signatures["assessment"]

    def sender(endpoint, raw, signed, *, origin=None, **kwargs):
        if origin and origin.split("//")[1].split(":")[0] == "assessment":
            reply = s.assessment.client.post(
                "/internal/v1/" + endpoint,
                content=raw,
                headers={"Content-Type": "application/json", "X-HR-Signature": signed},
            )
            if reply.status_code != 200:
                raise HTTPException(reply.status_code)
            return reply.content, reply.headers["X-HR-Signature"]
        return original(endpoint, raw, signed, origin=origin, **kwargs)

    s.notice_sender = sender
    for cls, field in ((MarketAccess, "market_access"), (ProcessingAccess, "processing_access")):
        access = cls(s.notification.app.state.settings)
        access._signatures, access._send = s.signatures["notification"], sender
        setattr(s.notification.app.state, field, access)
    return s.notification


def deliver(s):
    events = [
        EventEnvelope.model_validate(row.envelope)
        for row in rows(s, Outbox)
        if row.envelope["event_type"] == "assessment.company_notification_requested.v1"
    ]
    for event in events:
        with Session(s.notification.app.state.engine) as db, db.begin():
            process_company_notice(db, event, s.notification.app.state.market_access)
    return events


@pytest.fixture
def scheduled(company, service):
    s = company
    approved(s)
    assert subscribe(s).status_code == 200
    notification(s, service)
    return s


def test_subscription_opt_in_decline_cancel_and_recurring_epoch(scheduled):
    s = scheduled
    assert subscribe(s).json()["version"] == 2
    reply = schedule(s, interval_seconds=86400, max_occurrences=3)
    assert reply.status_code == 201, reply.text
    schedule_id = reply.json()["schedule_id"]
    assert subscribe(s, "cancelled", 2, "cancel").status_code == 200
    assert rows(s, CompanySchedule)[0].status == "cancelled"
    assert rows(s, CompanyJob)[0].status == "cancelled"
    assert subscribe(s, "active", 3, "resubscribe").status_code == 200
    assert not tick(s, datetime.now(UTC) + timedelta(days=30))
    assert rows(s, CompanyAssignment) == []
    assert subscribe(s, "declined", 4, "decline").status_code == 200
    assert schedule(s, "second").status_code == 409
    assert (
        s.assessment.client.get(f"/v1/company-task-schedules/{schedule_id}", headers=s.auth).json()[
            "status"
        ]
        == "cancelled"
    )
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["confirmed_grade"]
        == "middle"
    )


def test_one_time_schedule_atomic_assignment_and_notification_dedup(scheduled):
    s = scheduled
    reply = schedule(s)
    assert reply.status_code == 201, reply.text
    assert tick(s)
    assert len(rows(s, CompanyAssignment)) == 1
    assert rows(s, CompanySchedule)[0].status == "completed"
    assert tick(s)  # Marketing notice intent.
    events = deliver(s)
    deliver(s)
    assert len(events) == 1
    assert len(rows(s.notification, NotificationRow)) == 1
    assert (
        s.notification.client.get("/v1/notifications", headers=s.auth).json() == []
    )  # Default advertising opt-out.
    assert (
        s.notification.client.put(
            "/v1/notifications/preferences",
            headers=headers(s.auth, "pref", 1),
            json={"in_app": True, "marketing_in_app": True},
        ).status_code
        == 200
    )
    notices = s.notification.client.get("/v1/notifications", headers=s.auth).json()
    assert len(notices) == 1 and notices[0]["category"] == "marketing"
    assert "invitation_id" not in notices[0] and "assignment_id" in notices[0]
    notice_path = "/v1/notifications/" + notices[0]["notice_id"] + "/read"
    assert (
        s.notification.client.post(notice_path, headers=headers(s.auth, "read", 1)).status_code
        == 200
    )
    assert subscribe(s, "cancelled", 2, "cancel").status_code == 200
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []
    late = events[0].model_copy(update={"event_id": uuid4()})
    with Session(s.notification.app.state.engine) as db, db.begin():
        assert process_company_notice(db, late, s.notification.app.state.market_access)
    assert rows(s.notification, NotificationRow) == []
    assert subscribe(s, "active", 3, "again").status_code == 200
    with Session(s.notification.app.state.engine) as db, db.begin():
        process_company_notice(
            db,
            late.model_copy(update={"event_id": uuid4()}),
            s.notification.app.state.market_access,
        )
    assert rows(s.notification, NotificationRow) == []


def test_recurring_no_catchup_bursts_global_frequency_and_active_duplicate(scheduled):
    s = scheduled
    start = datetime.now(UTC)
    assert (
        schedule(
            s, starts_at=start.isoformat(), interval_seconds=86400, max_occurrences=3
        ).status_code
        == 201
    )
    assert tick(s, start + timedelta(seconds=1))
    assert tick(s, start + timedelta(seconds=2))
    assert not tick(s, start + timedelta(hours=2))
    assert tick(s, start + timedelta(days=5))  # Active previous assignment defers the next issue.
    assert len(rows(s, CompanyAssignment)) == 1
    job = next(j for j in rows(s, CompanyJob) if j.kind == "assign")
    assert job.error == "rate_limited" and job.status == "pending"
    first = rows(s, CompanyAssignment)[0]
    assert (
        s.assessment.client.post(
            f"/v1/company-assignments/{first.assignment_id}/decline",
            headers=headers(s.auth, "decline", 1),
        ).status_code
        == 200
    )
    with Session(s.assessment.app.state.engine) as db, db.begin():
        db.get(CompanyJob, job.job_id).next_at = start + timedelta(days=5)
    assert tick(s, start + timedelta(days=5, seconds=1))
    assert len(rows(s, CompanyAssignment)) == 2
    assert rows(s, CompanySchedule)[0].issued_count == 2
    assert tick(s, start + timedelta(days=5, seconds=1))
    assert not tick(s, start + timedelta(days=5, seconds=2))


@pytest.mark.parametrize("reason", ["consent", "cancel", "withdraw", "member"])
def test_permission_changes_cancel_due_work(scheduled, reason):
    s = scheduled
    assert schedule(s).status_code == 201
    if reason == "consent":
        assert (
            s.privacy.client.post(
                f"/v1/consents/{s.subscription_consent}/revoke",
                headers=headers(s.auth, "revoke", 1),
            ).status_code
            == 200
        )
    elif reason == "cancel":
        assert subscribe(s, "cancelled", 2, "cancel").status_code == 200
    elif reason == "withdraw":
        assert (
            s.assessment.client.post(
                f"/v1/company-task-proposals/{s.proposal['proposal_id']}/withdraw",
                json={"reason": "Withdraw"},
                headers=headers(s.employer_auth, "withdraw", s.proposal["version"]),
            ).status_code
            == 200
        )
    else:
        from reverse_hr.services.employer.domain.employer import Membership

        with Session(s.employer.app.state.engine) as db, db.begin():
            db.scalar(
                select(Membership).where(Membership.subject == str(s.recruiter_id))
            ).status = "revoked"
    tick(s)
    assert rows(s, CompanyAssignment) == []
    assert rows(s, CompanyJob)[0].status == "cancelled"


def test_worker_retries_unavailable_permission_without_partial_effects(scheduled):
    s = scheduled
    assert schedule(s).status_code == 201
    original = s.assessment.app.state.market_access._send
    s.assessment.app.state.market_access._send = Mock(side_effect=OSError("offline"))
    now = datetime.now(UTC)
    assert tick(s, now)
    assert rows(s, CompanyAssignment) == []
    job = rows(s, CompanyJob)[0]
    assert job.status == "pending" and job.error == "permission_unavailable" and job.attempts == 1
    assert not tick(s, now)
    s.assessment.app.state.market_access._send = original
    assert tick(s, job.next_at.replace(tzinfo=UTC) + timedelta(seconds=1))
    assert len(rows(s, CompanyAssignment)) == 1


def test_two_workers_do_not_issue_twice(scheduled):
    s = scheduled
    assert schedule(s).status_code == 201
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(tick, s) for _ in range(2)]
        [f.result(timeout=30) for f in futures]
    assert len(rows(s, CompanyAssignment)) == 1
    assert rows(s, CompanySchedule)[0].issued_count == 1


def test_service_reminder_and_in_app_switch(scheduled):
    s = scheduled
    assert schedule(s).status_code == 201
    assert tick(s)
    assert tick(s)
    assignment = rows(s, CompanyAssignment)[0]
    assert tick(s, assignment.expires_at.replace(tzinfo=UTC) - timedelta(hours=12))
    deliver(s)
    notices = s.notification.client.get("/v1/notifications", headers=s.auth).json()
    assert [n["kind"] for n in notices] == ["deadline_reminder"]
    assert notices[0]["category"] == "service"
    assert (
        s.notification.client.put(
            "/v1/notifications/preferences",
            headers=headers(s.auth, "mute", 1),
            json={"in_app": False},
        ).status_code
        == 200
    )
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []


def test_result_ready_waits_for_review_and_company_disclosure(completed, service):
    s = completed
    notification(s, service)
    assert tick(s)
    job = next(j for j in rows(s, CompanyJob) if j.kind == "result_ready")
    assert job.status == "pending" and job.error == "evidence_pending"
    confirm(s)
    assert tick(s, job.next_at.replace(tzinfo=UTC) + timedelta(seconds=1))
    events = deliver(s)
    assert len(events) == 2 and {n.kind for n in rows(s, CompanyNoticeSource)} == {"result_ready"}
    assert (
        s.notification.client.get("/v1/notifications", headers=s.auth).json()[0]["category"]
        == "service"
    )
    assert len(s.notification.client.get("/v1/notifications", headers=s.employer_auth).json()) == 1
    assert (
        s.privacy.client.post(
            f"/v1/company-result-grants/{s.grant['grant_id']}/revoke",
            headers=headers(s.auth, "revoke", 1),
        ).status_code
        == 200
    )
    assert s.notification.client.get("/v1/notifications", headers=s.employer_auth).json() == []
    assert len(s.notification.client.get("/v1/notifications", headers=s.auth).json()) == 1


def test_signed_consumer_commit_before_ack_retry_and_duplicate(scheduled):
    s = scheduled
    schedule(s)
    tick(s)
    tick(s)
    event = EventEnvelope.model_validate(
        next(
            r.envelope
            for r in rows(s, Outbox)
            if r.envelope["event_type"] == "assessment.company_notification_requested.v1"
        )
    )
    consumer = NotificationConsumer(
        s.notification.app.state.engine,
        s.signatures["notification"],
        s.notification.app.state.settings,
    )
    consumer.access._send = s.notice_sender
    raw, signed = s.signatures["assessment"].sign(event)
    channel = Mock()

    def committed_before_ack(**_):
        assert len(rows(s.notification, NotificationRow)) == 1

    channel.basic_ack.side_effect = committed_before_ack
    method = SimpleNamespace(exchange="events.assessment", delivery_tag=4)
    properties = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    consumer.access._send = Mock(side_effect=OSError("offline"))
    failed = Mock()
    consumer(failed, method, properties, raw)
    assert rows(s.notification, NotificationRow) == []
    assert failed.basic_publish.call_args.kwargs["exchange"] == "retry.notification"
    assert failed.basic_publish.call_args.kwargs["properties"].headers["hr-attempt"] == 1
    consumer.access._send = s.notice_sender
    consumer(channel, method, properties, raw)
    consumer(channel, method, properties, raw)
    assert channel.basic_ack.call_count == 2 and len(rows(s.notification, NotificationRow)) == 1
    assert not channel.basic_publish.called


def test_privacy_removes_jobs_and_late_notice_cannot_resurrect(scheduled):
    from tests.services.code_runner.test_code_runner import deletion

    s = scheduled
    schedule(s)
    tick(s)
    tick(s)
    events = deliver(s)
    event = deletion(s.candidate_id)
    with Session(s.assessment.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, event)
    with Session(s.notification.app.state.engine) as db, db.begin():
        assert delete_notifications(db, event)
    assert (
        rows(s, CompanySchedule) == []
        and rows(s, CompanyJob) == []
        and rows(s, CompanySubscription) == []
    )
    with Session(s.notification.app.state.engine) as db, db.begin():
        process_company_notice(
            db,
            events[0].model_copy(update={"event_id": uuid4()}),
            s.notification.app.state.market_access,
        )
    assert rows(s.notification, NotificationRow) == []
    assert not tick(s)


def test_schedule_constraints_frequency_and_populated_downgrade(scheduled):
    s = scheduled
    assert subscribe(s, version=2, key="weekly", min_interval_seconds=604800).status_code == 200
    assert schedule(s, interval_seconds=86400, max_occurrences=3).status_code == 409
    assert schedule(s, max_occurrences=3).status_code == 422
    assert schedule(s, starts_at="2026-01-01T00:00:00").status_code == 422
    assert schedule(s).status_code == 201
    assert (
        schedule(
            s,
            "duplicate",
            starts_at=rows(s, CompanySchedule)[0].starts_at.replace(tzinfo=UTC).isoformat(),
        ).status_code
        == 409
    )
    with pytest.raises(RuntimeError, match="company scheduling"):
        command.downgrade(migration_config(s.assessment.app.state.settings), "0013_assessment")
    assert s.assessment.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("action", ["unsubscribe", "revoke"])
def test_cancellation_between_external_check_and_commit_wins(scheduled, action):
    s = scheduled
    schedule(s)
    original = s.assessment.app.state.market_access._send
    changed = False

    def race(endpoint, *args, **kwargs):
        nonlocal changed
        response = original(endpoint, *args, **kwargs)
        if endpoint == "market/purpose-permission" and not changed:
            changed = True
            if action == "unsubscribe":
                assert subscribe(s, "cancelled", 2, "race").status_code == 200
            else:
                assert (
                    s.privacy.client.post(
                        f"/v1/consents/{s.subscription_consent}/revoke",
                        headers=headers(s.auth, "race", 1),
                    ).status_code
                    == 200
                )
        return response

    s.assessment.app.state.market_access._send = race
    assert tick(s)
    assert changed and rows(s, CompanyAssignment) == []
    assert rows(s, CompanyJob)[0].status == "cancelled"


def test_subscription_and_schedule_lists_ownership_and_opt_in_validation(scheduled):
    s = scheduled
    assert (
        len(s.assessment.client.get("/v1/company-task-subscriptions", headers=s.auth).json()) == 1
    )
    assert (
        s.assessment.client.get(
            "/v1/company-task-subscriptions", headers=s.employer_auth
        ).status_code
        == 403
    )
    assert subscribe(s, consent_id=None, version=2, key="missing").status_code == 422
    assert (
        subscribe(
            s, consent_id=consent(s, "assessment"), version=2, key="wrong-purpose"
        ).status_code
        == 409
    )
    response = schedule(s)
    assert response.status_code == 201
    assert len(s.assessment.client.get("/v1/company-task-schedules", headers=s.auth).json()) == 1
    assert s.assessment.client.get("/v1/company-task-schedules", headers=s.token()).json() == []
    assert (
        s.assessment.client.get(
            "/v1/company-task-schedules",
            headers=s.employer_auth,
            params={"organization_id": s.organization_id},
        ).status_code
        == 200
    )
    path = "/v1/company-task-schedules/" + response.json()["schedule_id"]
    assert (
        s.assessment.client.post(path + "/cancel", headers=headers(s.auth, "cancel", 1)).status_code
        == 200
    )
    assert not tick(s)


def test_notification_upgrade_preserves_legacy_service_preference(service):
    from sqlalchemy import text

    target = service("notification")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0002_notification")
    subject = str(uuid4())
    with target.app.state.engine.begin() as db:
        db.execute(
            text(
                "INSERT INTO notification_preferences (subject, in_app, version) "
                "VALUES (:subject, true, 2)"
            ),
            {"subject": subject},
        )
    command.upgrade(config, "head")
    from reverse_hr.services.notification.domain.notification import Preference

    with Session(target.app.state.engine) as db:
        row = db.get(Preference, subject)
        assert row.in_app and not row.marketing_in_app and row.version == 2
    assert target.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("started", [False, True])
def test_subscription_revoke_blocks_new_acceptance_but_preserves_accepted_session(
    scheduled, started
):
    s = scheduled
    assert schedule(s).status_code == 201
    assert tick(s)
    row = rows(s, CompanyAssignment)[0]
    s.assignment = {"assignment_id": row.assignment_id}
    s.assignment_path = "/v1/company-assignments/" + row.assignment_id
    grant(s)
    if started:
        response = accept(s)
        assert response.status_code == 201, response.text
        session_id = response.json()["session_id"]
        assert subscribe(s, "cancelled", 2, "unsubscribe").status_code == 200
        current = rows(s, CompanyAssignment)[0]
        assert current.status == "accepted" and current.session_id == session_id
        assert s.assessment.client.get(s.assignment_path, headers=s.auth).status_code == 200
    else:
        assert (
            s.privacy.client.post(
                f"/v1/consents/{s.subscription_consent}/revoke",
                headers=headers(s.auth, "revoke", 1),
            ).status_code
            == 200
        )
        assert accept(s).status_code == 409
        assert rows(s, CompanyAssignment)[0].session_id is None
