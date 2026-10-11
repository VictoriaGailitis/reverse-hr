"""Migrated databases and actual signed RPC for vacancies, applications and disclosure."""

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

from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.market_access import MarketAccess
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.services.hiring.domain.hiring import InvitationRow, Need
from reverse_hr.services.hiring.domain.hiring import process_deletion_request as erase_hiring
from reverse_hr.services.hiring.domain.hiring_dialogs import Dialog, EmployerBlock, Notice
from reverse_hr.services.hiring.domain.hiring_vacancies import (
    Application,
    ApplicationChange,
    Vacancy,
    VacancyDecision,
)
from reverse_hr.services.notification.consumer import NotificationConsumer
from reverse_hr.services.notification.domain.notification import NotificationRow, process_notice
from reverse_hr.services.notification.domain.notification import (
    process_deletion_request as erase_notification,
)
from reverse_hr.shared.db import IdempotencyRecord
from tests.integration.test_matching_hiring import consent, publication
from tests.integration.test_matching_hiring import setup as market_setup
from tests.services.code_runner.test_code_runner import deletion
from tests.services.hiring.test_hiring_dialogs import deliver_grant, deliver_notices, events
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture
setup = market_setup


def spec(s, **changes):
    return (
        dict(
            organization_id=s.organization_id,
            title="Backend engineer",
            description="Build reliable APIs",
            employer_contact="recruiter@example.test",
            salary=dict(tax_basis="gross", minimum=100000, maximum=200000),
            requirements=dict(
                organization_id=s.organization_id,
                specialization="backend",
                confirmed_grade="middle",
                required_skills=["python"],
            ),
        )
        | changes
    )


def create(s, key="vacancy", **changes):
    return s.hiring.client.post(
        "/v1/vacancies", json=spec(s, **changes), headers=headers(s.employer_auth, key)
    )


def vacancy_action(s, row, action, *, auth=None, body=None, key=None):
    return s.hiring.client.post(
        f"/v1/vacancies/{row['vacancy_id']}/{action}",
        json=body,
        headers=headers(
            auth or s.employer_auth, key or action + str(row["version"]), row["version"]
        ),
    )


def publish(s):
    row = create(s).json()
    response = vacancy_action(s, row, "submit")
    assert response.status_code == 200, response.text
    response = vacancy_action(
        s,
        response.json(),
        "review",
        auth=s.moderator,
        body=dict(outcome="approved", reason="Independent synthetic review"),
    )
    assert response.status_code == 200, response.text
    response = vacancy_action(s, response.json(), "publish")
    assert response.status_code == 200, response.text
    s.vacancy = response.json()
    s.vpath = "/v1/vacancies/" + s.vacancy["vacancy_id"]
    return s.vacancy


def apply(s, key="apply", **changes):
    return s.hiring.client.post(
        s.vpath + "/applications",
        json=dict(vacancy_version=s.vacancy["version"]) | changes,
        headers=headers(s.auth, key),
    )


def app_action(s, row, action, *, auth=None, body=None, key=None):
    return s.hiring.client.post(
        f"/v1/applications/{row['application_id']}/{action}",
        json=body,
        headers=headers(
            auth or s.employer_auth, key or action + str(row["version"]), row["version"]
        ),
    )


def notification(s, service):
    s.notification = service("notification")
    for cls, field in ((MarketAccess, "market_access"), (ProcessingAccess, "processing_access")):
        access = cls(s.notification.app.state.settings)
        access._signatures, access._send = s.signatures["notification"], s.sender
        setattr(s.notification.app.state, field, access)


def rows(s, model):
    with Session(s.hiring.app.state.engine) as db:
        return list(db.scalars(select(model)))


@pytest.fixture
def published(setup, service):
    publish(setup)
    notification(setup, service)
    return setup


def accept_application(s, row):
    reply = app_action(s, row, "invite", body={})
    assert reply.status_code == 200, reply.text
    row = reply.json()
    s.iid = row["invitation_id"]
    s.path = "/v1/dialogs/" + s.iid
    s.disclosure = consent(s, "contact_disclosure")
    accepted = s.hiring.client.post(
        f"/v1/invitations/{s.iid}/accept",
        json=dict(disclosure_consent_id=s.disclosure),
        headers=headers(s.auth, "accept", 1),
    )
    assert accepted.status_code == 200, accepted.text
    deliver_grant(s)
    return row


def test_vacancy_moderation_revision_and_managed_matching_need(setup):
    s = setup
    row = create(s).json()
    path = "/v1/vacancies/" + row["vacancy_id"]
    assert s.hiring.client.get("/v1/vacancies", headers=s.auth).json() == []
    assert vacancy_action(s, row, "publish").status_code == 409
    row = vacancy_action(s, row, "submit").json()
    queue = s.hiring.client.get("/v1/vacancy-reviews", headers=s.moderator).json()
    assert [v["vacancy_id"] for v in queue] == [row["vacancy_id"]]
    assert (
        vacancy_action(
            s,
            row,
            "review",
            auth=s.token(s.recruiter_id, ("company_moderator",), amr=["mfa"]),
            body=dict(outcome="approved", reason="Own vacancy"),
        ).status_code
        == 403
    )
    assert (
        vacancy_action(
            s,
            row,
            "review",
            auth=s.token(roles=("company_moderator",)),
            body=dict(outcome="approved", reason="No MFA"),
        ).status_code
        == 403
    )
    row = vacancy_action(
        s, row, "review", auth=s.moderator, body=dict(outcome="approved", reason="Reviewed")
    ).json()
    row = vacancy_action(s, row, "publish").json()
    assert s.hiring.client.get(path, headers=s.auth).json()["status"] == "published"
    assert s.hiring.client.get(
        "/v1/vacancies?specialization=backend&confirmed_grade=middle", headers=s.auth
    ).json() == [row]
    assert s.hiring.client.get("/v1/vacancies?specialization=frontend", headers=s.auth).json() == []
    with Session(s.hiring.app.state.engine) as db:
        need = db.get(Need, row["need_id"])
        assert need.spec["status"] == "published"
    assert (
        s.hiring.client.put(
            "/v1/hiring-needs/" + row["need_id"],
            json=dict(
                organization_id=s.organization_id,
                specialization="backend",
                confirmed_grade="middle",
                status="published",
            ),
            headers=headers(s.employer_auth, "bypass", 4),
        ).status_code
        == 409
    )
    edited = s.hiring.client.put(
        path,
        json=spec(s, description="Changed requirements"),
        headers=headers(s.employer_auth, "edit", row["version"]),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["revision"] == 2 and edited.json()["status"] == "draft"
    assert s.hiring.client.get("/v1/vacancies", headers=s.auth).json() == []
    assert vacancy_action(s, edited.json(), "publish").status_code == 409
    with Session(s.hiring.app.state.engine) as db:
        assert db.get(Need, row["need_id"]).spec["status"] == "draft"
    history = s.hiring.client.get(path + "/reviews", headers=s.employer_auth).json()
    assert len(history) == 1 and history[0]["revision"] == 1
    assert s.hiring.client.get(path + "/reviews", headers=s.auth).status_code == 403


@pytest.mark.parametrize("change", ["organization", "salary", "requirements"])
def test_vacancy_binding_and_salary_validation(setup, change):
    s = setup
    body = spec(s)
    if change == "organization":
        body["requirements"]["organization_id"] = str(uuid4())
    elif change == "salary":
        body["salary"]["maximum"] = 1
    else:
        body["requirements"]["status"] = "published"
    assert (
        s.hiring.client.post(
            "/v1/vacancies", json=body, headers=headers(s.employer_auth, "bad")
        ).status_code
        == 422
    )
    assert rows(s, Vacancy) == []


def test_rejected_vacancy_requires_edit_and_new_review(setup):
    s = setup
    row = vacancy_action(s, create(s).json(), "submit").json()
    row = vacancy_action(
        s, row, "review", auth=s.moderator, body=dict(outcome="rejected", reason="Unclear terms")
    ).json()
    assert row["status"] == "rejected"
    assert vacancy_action(s, row, "submit").status_code == 409
    row = s.hiring.client.put(
        "/v1/vacancies/" + row["vacancy_id"],
        json=spec(s),
        headers=headers(s.employer_auth, "edit", row["version"]),
    ).json()
    row = vacancy_action(s, row, "submit").json()
    row = vacancy_action(
        s, row, "review", auth=s.moderator, body=dict(outcome="approved", reason="Fixed")
    ).json()
    assert len(rows(s, VacancyDecision)) == 2
    assert vacancy_action(s, row, "publish").status_code == 200


def test_apply_preview_dedup_live_card_and_no_contact_disclosure(published):
    s = published
    preview = s.hiring.client.get(s.vpath + "/application-preview", headers=s.auth).json()
    assert not preview["contacts_disclosed"] and "email" not in preview["shared_fields"]
    reply = apply(s)
    assert reply.status_code == 201, reply.text
    app = reply.json()
    assert (
        app["status"] == "submitted" and app["dialog_id"] is None and app["invitation_id"] is None
    )
    assert apply(s).json() == app
    assert apply(s, "duplicate").status_code == 409
    assert len(rows(s, Application)) == 1 and len(rows(s, ApplicationChange)) == 1
    path = "/v1/applications/" + app["application_id"]
    card = s.hiring.client.get(path + "/candidate", headers=s.employer_auth)
    assert card.status_code == 200 and card.json()["confirmed_grade"] == "middle"
    assert not {"email", "phone", "declared_grade"} & card.json().keys()
    assert s.hiring.client.get(path, headers=s.token()).status_code in {403, 404, 409}
    assert s.hiring.client.get(path + "/candidate", headers=s.auth).status_code == 403
    assert s.hiring.client.get("/v1/applications", headers=s.auth).json() == [app]
    assert s.hiring.client.get("/v1/applications", headers=s.token()).json() == []
    assert s.hiring.client.get(
        "/v1/applications", headers=s.employer_auth, params=dict(organization_id=s.organization_id)
    ).json() == [app]
    assert publication(s, False).status_code == 200
    assert s.hiring.client.get(path + "/candidate", headers=s.employer_auth).status_code == 409
    assert s.hiring.client.get(path, headers=s.auth).status_code == 200
    assert app_action(s, app, "invite", body={}).status_code == 409


def test_application_hiring_flow_invitation_privacy_dialog_and_statuses(published):
    s = published
    app = apply(s).json()
    assert app_action(s, app, "status", body=dict(status="hired")).status_code == 409
    app = app_action(s, app, "status", body=dict(status="reviewing")).json()
    app = accept_application(s, app)
    path = "/v1/applications/" + app["application_id"]
    assert s.hiring.client.get(path, headers=s.auth).json()["dialog_id"] == s.iid
    assert len(rows(s, Dialog)) == 1
    sent = s.hiring.client.post(
        s.path + "/messages",
        json=dict(text="Discuss the role"),
        headers=headers(s.auth, "message", 1),
    )
    assert sent.status_code == 201, sent.text
    for status in ("interview", "offer", "hired"):
        response = app_action(s, app, "status", body=dict(status=status))
        assert response.status_code == 200, response.text
        app = response.json()
    assert s.hiring.client.get(path + "/history", headers=s.auth).json()[-1]["status"] == "hired"
    assert app_action(s, app, "withdraw", auth=s.auth).status_code == 409
    assert app_action(s, app, "status", body=dict(status="reviewing")).status_code == 409
    deliver_notices(s)
    deliver_notices(s)
    notices = s.notification.client.get("/v1/notifications", headers=s.auth).json()
    applications = [n for n in notices if n.get("application_id")]
    assert applications and all(
        n["category"] == "service" and "invitation_id" not in n for n in applications
    )
    assert len(rows(s, Notice)) == len(events(s, "notification_requested"))


@pytest.mark.parametrize("action", ["withdraw", "reject", "decline", "revoke"])
def test_application_terminal_transition_closes_linked_access(published, action):
    s = published
    app = apply(s).json()
    if action in {"withdraw", "reject"}:
        app = accept_application(s, app)
        response = (
            app_action(s, app, "withdraw", auth=s.auth)
            if action == "withdraw"
            else app_action(s, app, "status", body=dict(status="rejected"))
        )
    else:
        app = app_action(s, app, "invite", body={}).json()
        s.iid = app["invitation_id"]
        response = s.hiring.client.post(
            f"/v1/invitations/{s.iid}/{'decline' if action == 'decline' else 'revoke'}",
            headers=headers(s.auth if action == "decline" else s.employer_auth, "close", 1),
        )
    assert response.status_code == 200, response.text
    path = "/v1/applications/" + app["application_id"]
    current = s.hiring.client.get(path, headers=s.auth).json()
    assert current["status"] == ("withdrawn" if action in {"withdraw", "decline"} else "rejected")
    assert s.hiring.client.get(path + "/candidate", headers=s.employer_auth).status_code == 409
    assert (
        s.hiring.client.get(
            f"/v1/invitations/{s.iid}/contacts", headers=s.employer_auth
        ).status_code
        == 409
    )
    assert (
        s.hiring.client.post(
            f"/v1/dialogs/{s.iid}/messages",
            json=dict(text="Late message"),
            headers=headers(s.employer_auth, "late", 1),
        ).status_code
        == 404
    )


def test_invitation_acceptance_and_revoke_consent_gate_next_stage(published):
    s = published
    app = app_action(s, apply(s).json(), "invite", body={}).json()
    assert app_action(s, app, "status", body=dict(status="interview")).status_code == 409
    s.iid = app["invitation_id"]
    s.disclosure = consent(s, "contact_disclosure")
    assert (
        s.hiring.client.post(
            f"/v1/invitations/{s.iid}/accept",
            json=dict(disclosure_consent_id=s.disclosure),
            headers=headers(s.auth, "accept", 1),
        ).status_code
        == 200
    )
    assert app_action(s, app, "status", body=dict(status="interview")).status_code == 409
    deliver_grant(s)
    assert (
        s.privacy.client.post(
            f"/v1/consents/{s.disclosure}/revoke", headers=headers(s.auth, "revoke", 1)
        ).status_code
        == 200
    )
    assert app_action(s, app, "status", body=dict(status="interview")).status_code == 409
    assert app_action(s, app, "withdraw", auth=s.auth).status_code == 200


def test_archive_and_edit_block_new_application_preserve_existing_snapshot(published):
    s = published
    app = apply(s).json()
    updated = s.hiring.client.put(
        s.vpath,
        json=spec(s, title="Different title"),
        headers=headers(s.employer_auth, "edit", s.vacancy["version"]),
    ).json()
    assert apply(s, "stale").status_code in {403, 409}
    stored = s.hiring.client.get("/v1/applications/" + app["application_id"], headers=s.auth).json()
    assert stored["vacancy_snapshot"]["title"] == "Backend engineer"
    assert vacancy_action(s, updated, "archive").status_code == 200
    assert s.hiring.client.get("/v1/vacancies", headers=s.auth).json() == []
    invited = app_action(s, app, "invite", body={})
    assert invited.status_code == 200, invited.text
    invitation = s.hiring.client.get(
        "/v1/invitations/" + invited.json()["invitation_id"], headers=s.auth
    ).json()
    assert invitation["description"] == app["vacancy_snapshot"]["description"]


@pytest.mark.parametrize("action", ["unpublish", "consent", "membership", "block"])
def test_live_permission_changes_block_new_applications(published, action):
    s = published
    if action == "unpublish":
        assert publication(s, False).status_code == 200
    elif action == "consent":
        assert (
            s.privacy.client.post(
                f"/v1/consents/{s.consent}/revoke", headers=headers(s.auth, "revoke", 1)
            ).status_code
            == 200
        )
    elif action == "membership":
        from reverse_hr.services.employer.domain.employer import Membership

        with Session(s.employer.app.state.engine) as db, db.begin():
            db.scalar(
                select(Membership).where(Membership.subject == str(s.recruiter_id))
            ).status = "revoked"
    else:
        with Session(s.hiring.app.state.engine) as db, db.begin():
            db.add(
                EmployerBlock(candidate_id=str(s.candidate_id), organization_id=s.organization_id)
            )
    assert apply(s).status_code == 409
    assert rows(s, Application) == []


def test_parallel_apply_dedup_and_withdraw_invite_race(published):
    s = published
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda key: apply(s, key), ["first", "second"]))
    assert sorted(r.status_code for r in replies) == [201, 409]
    app = next(r.json() for r in replies if r.status_code == 201)
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(app_action, s, app, "invite", body={}),
            pool.submit(app_action, s, app, "withdraw", auth=s.auth),
        ]
        replies = [f.result(timeout=30) for f in futures]
    assert sorted(r.status_code for r in replies) == [200, 409]
    assert len(rows(s, Application)) == 1 and len(rows(s, InvitationRow)) <= 1
    assert len(rows(s, ApplicationChange)) == 2


def test_application_notification_retry_ack_dedup_and_privacy_cleanup(published):
    s = published
    app = apply(s).json()
    event = events(s, "notification_requested")[0]
    consumer = NotificationConsumer(
        s.notification.app.state.engine,
        s.signatures["notification"],
        s.notification.app.state.settings,
    )
    consumer.access._send = Mock(side_effect=OSError("offline"))
    raw, signed = s.signatures["hiring"].sign(event)
    method = SimpleNamespace(exchange="events.hiring", delivery_tag=1)
    properties = SimpleNamespace(headers=signed, message_id=str(event.event_id))
    failed = Mock()
    consumer(failed, method, properties, raw)
    assert failed.basic_publish.call_args.kwargs["exchange"] == "retry.notification"
    consumer.access._send = s.sender
    channel = Mock()

    def committed(**_):
        with Session(s.notification.app.state.engine) as db:
            assert (
                db.get(NotificationRow, str(event.aggregate_id)).application_id
                == app["application_id"]
            )

    channel.basic_ack.side_effect = committed
    consumer(channel, method, properties, raw)
    consumer(channel, method, properties, raw)
    assert channel.basic_ack.call_count == 2
    with Session(s.hiring.app.state.engine) as db, db.begin():
        assert erase_hiring(db, deletion(s.candidate_id))
    with Session(s.notification.app.state.engine) as db, db.begin():
        assert erase_notification(db, deletion(s.candidate_id))
    assert rows(s, Application) == [] and rows(s, ApplicationChange) == []
    with Session(s.notification.app.state.engine) as db, db.begin():
        process_notice(
            db,
            event.model_copy(update=dict(event_id=uuid4())),
            s.notification.app.state.market_access,
        )
        assert db.scalar(select(NotificationRow)) is None
    assert (
        s.hiring.client.get("/v1/applications/" + app["application_id"], headers=s.auth).status_code
        == 404
    )
    with Session(s.hiring.app.state.engine) as db:
        assert not any(
            app["application_id"] in r.response for r in db.scalars(select(IdempotencyRecord))
        )


def test_provider_outage_rolls_back_application_and_notifications(published):
    s = published
    original = s.hiring.app.state.market_access._send
    s.hiring.app.state.market_access._send = Mock(side_effect=OSError("offline"))
    assert apply(s).status_code == 503
    assert rows(s, Application) == [] and rows(s, Notice) == []
    s.hiring.app.state.market_access._send = original
    assert apply(s).status_code == 201


def test_populated_downgrade_keeps_ready_schema(published):
    s = published
    apply(s)
    deliver_notices(s)
    for target in (s.hiring, s.notification):
        with pytest.raises(RuntimeError):
            command.downgrade(migration_config(target.app.state.settings), "base")
        assert target.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("action", ["archive", "edit"])
def test_archive_edit_race_with_apply_keeps_snapshot_consistent(published, action):
    s = published

    def mutate():
        if action == "archive":
            return vacancy_action(s, s.vacancy, "archive")
        return s.hiring.client.put(
            s.vpath,
            json=spec(s, title="Changed"),
            headers=headers(s.employer_auth, "edit", s.vacancy["version"]),
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        submitted = pool.submit(apply, s)
        updated = pool.submit(mutate)
        reply, update = submitted.result(timeout=30), updated.result(timeout=30)
    assert update.status_code == 200
    assert reply.status_code in {201, 403, 409}
    applications = rows(s, Application)
    assert len(applications) == (1 if reply.status_code == 201 else 0)
    if applications:
        assert applications[0].vacancy_snapshot["title"] == "Backend engineer"
        assert applications[0].vacancy_version == s.vacancy["version"]


@pytest.mark.parametrize("subject", ["candidate", "creator", "reviewer"])
def test_privacy_cleanup_vacancy_and_application_owners(published, subject):
    s = published
    app = apply(s).json()
    actor_id = (
        s.candidate_id
        if subject == "candidate"
        else s.recruiter_id
        if subject == "creator"
        else rows(s, VacancyDecision)[0].reviewer_id
    )
    with Session(s.hiring.app.state.engine) as db, db.begin():
        assert erase_hiring(db, deletion(actor_id))
    if subject in {"candidate", "creator"}:
        assert rows(s, Application) == [] and rows(s, ApplicationChange) == []
        assert not any(row.application_id == app["application_id"] for row in rows(s, Notice))
    if subject == "creator":
        assert rows(s, Vacancy) == [] and rows(s, VacancyDecision) == []
    if subject == "reviewer":
        assert rows(s, Vacancy)[0].status == "draft"
        assert rows(s, VacancyDecision) == []
        with Session(s.hiring.app.state.engine) as db:
            assert db.get(Need, s.vacancy["need_id"]).spec["status"] == "draft"
        assert s.hiring.client.get("/v1/vacancies", headers=s.auth).json() == []


def test_actual_application_contacts_require_acceptance_and_grant(published):
    s = published
    assert (
        s.candidate.client.put(
            "/v1/candidates/me/contacts",
            json=dict(email="candidate@example.test", phone="+123456789"),
            headers=headers(s.auth, "contacts"),
        ).status_code
        == 200
    )
    app = app_action(s, apply(s).json(), "invite", body={}).json()
    s.iid = app["invitation_id"]
    contacts = f"/v1/invitations/{s.iid}/contacts"
    assert s.hiring.client.get(contacts, headers=s.employer_auth).status_code == 409
    s.disclosure = consent(s, "contact_disclosure")
    assert (
        s.hiring.client.post(
            f"/v1/invitations/{s.iid}/accept",
            json=dict(disclosure_consent_id=s.disclosure),
            headers=headers(s.auth, "accept", 1),
        ).status_code
        == 200
    )
    assert s.hiring.client.get(contacts, headers=s.employer_auth).status_code == 409
    deliver_grant(s)
    assert (
        s.hiring.client.get(contacts, headers=s.employer_auth).json()["email"]
        == "candidate@example.test"
    )
    assert app_action(s, app, "withdraw", auth=s.auth).status_code == 200
    assert s.hiring.client.get(contacts, headers=s.employer_auth).status_code == 409


def test_application_notice_rejects_wrong_binding_and_revoked_recipient(published):
    s = published
    apply(s)
    event = events(s, "notification_requested")[0]
    wrong = event.model_copy(
        update=dict(event_id=uuid4(), payload=event.payload | dict(application_id=uuid4()))
    )
    with Session(s.notification.app.state.engine) as db, db.begin():
        with pytest.raises(HTTPException):
            process_notice(db, wrong, s.notification.app.state.market_access)
        assert db.scalar(select(NotificationRow)) is None
    from reverse_hr.services.employer.domain.employer import Membership

    with Session(s.employer.app.state.engine) as db, db.begin():
        db.scalar(
            select(Membership).where(Membership.subject == str(s.recruiter_id))
        ).status = "revoked"
    deliver_notices(s)
    with Session(s.notification.app.state.engine) as db:
        assert db.scalar(select(NotificationRow)) is None


def test_expired_invitation_is_visible_and_cannot_advance(published):
    s = published
    app = app_action(s, apply(s).json(), "invite", body={}).json()
    with Session(s.hiring.app.state.engine) as db, db.begin():
        db.get(InvitationRow, app["invitation_id"]).expires_at = datetime.now(UTC) - timedelta(
            seconds=1
        )
    current = s.hiring.client.get(
        "/v1/applications/" + app["application_id"], headers=s.auth
    ).json()
    assert current["invitation_status"] == "expired"
    assert app_action(s, app, "status", body=dict(status="interview")).status_code == 409
    assert app_action(s, app, "withdraw", auth=s.auth).status_code == 200


def test_matching_uses_only_current_published_managed_vacancy(published):
    s = published
    payload = dict(organization_id=s.organization_id, need_id=s.vacancy["need_id"], mode="demo")
    reply = s.matching.client.post(
        "/v1/matches", json=payload, headers=headers(s.employer_auth, "match")
    )
    assert reply.status_code == 201, reply.text
    assert [row["candidate_id"] for row in reply.json()["matches"]] == [str(s.candidate_id)]
    archived = vacancy_action(s, s.vacancy, "archive")
    assert archived.status_code == 200
    assert (
        s.matching.client.post(
            "/v1/matches", json=payload, headers=headers(s.employer_auth, "late")
        ).status_code
        == 409
    )
    assert (
        s.matching.client.get(
            "/v1/matches/" + reply.json()["snapshot_id"], headers=s.employer_auth
        ).status_code
        == 409
    )


def test_reviewer_tombstone_blocks_publication_and_matching_before_local_cleanup(published):
    s = published
    reviewer = rows(s, VacancyDecision)[0].reviewer_id
    original = s.hiring.app.state.processing_access.check

    def check(subject):
        if str(subject) == reviewer:
            raise HTTPException(409)
        return original(subject)

    s.hiring.app.state.processing_access.check = check
    assert s.hiring.client.get("/v1/vacancies", headers=s.auth).json() == []
    assert s.hiring.client.get(s.vpath, headers=s.auth).status_code == 409
    assert apply(s).status_code == 409
    assert (
        s.matching.client.post(
            "/v1/matches",
            json=dict(organization_id=s.organization_id, need_id=s.vacancy["need_id"], mode="demo"),
            headers=headers(s.employer_auth, "match"),
        ).status_code
        == 409
    )


def test_deleting_vacancy_creator_closes_invitation_sent_by_another_employee(published):
    s = published
    app = apply(s).json()
    other_id = uuid4()
    other = s.token(other_id, ("employer",))
    added = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json=dict(subject=str(other_id), role="recruiter"),
        headers=headers(s.employer_auth, "member", 2),
    )
    assert added.status_code == 201, added.text
    app = app_action(s, app, "invite", auth=other, body={}).json()
    s.iid = app["invitation_id"]
    s.disclosure = consent(s, "contact_disclosure")
    assert (
        s.hiring.client.post(
            f"/v1/invitations/{s.iid}/accept",
            json=dict(disclosure_consent_id=s.disclosure),
            headers=headers(s.auth, "accept", 1),
        ).status_code
        == 200
    )
    deliver_grant(s)
    original = s.hiring.app.state.processing_access.check

    def creator_deleted(subject):
        if str(subject) == str(s.recruiter_id):
            raise HTTPException(409)
        return original(subject)

    s.hiring.app.state.processing_access.check = creator_deleted
    assert (
        s.hiring.client.get(f"/v1/invitations/{s.iid}/contacts", headers=other).status_code == 409
    )
    s.hiring.app.state.processing_access.check = original
    with Session(s.hiring.app.state.engine) as db, db.begin():
        assert erase_hiring(db, deletion(s.recruiter_id))
    assert rows(s, Application) == [] and rows(s, InvitationRow) == [] and rows(s, Dialog) == []
    with Session(s.hiring.app.state.engine) as db:
        assert not any(
            s.iid in row.response or s.iid in row.operation
            for row in db.scalars(select(IdempotencyRecord))
        )
    assert (
        s.hiring.client.get(f"/v1/invitations/{s.iid}/contacts", headers=other).status_code == 404
    )
