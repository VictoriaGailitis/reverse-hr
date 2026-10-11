"""Migrated owners, signed catalog/consent/notice RPC and real notification consumer."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.protocols.market_access import MarketAccess
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.services.assessment.domain.assessment_generation import (
    GenerationJob,
    GenerationReference,
)
from reverse_hr.services.candidate.domain.candidate import (
    CandidateProfile,
    process_deletion_request,
)
from reverse_hr.services.candidate.domain.candidate_recommendations import (
    TaskRecommendation,
    TaskSubscription,
    run_one,
)
from reverse_hr.services.notification.domain.notification import (
    NotificationRow,
    process_task_notice,
)
from reverse_hr.shared.db import Outbox
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures


@pytest.fixture
def setup(service, token, signatures):
    targets = {
        name: service(name) for name in ("candidate", "privacy", "assessment", "notification")
    }

    def send(route, raw, signature, *, origin=None, **kwargs):
        owner = origin.split("//")[1].split(":")[0] if origin else "privacy"
        reply = targets[owner].client.post(
            "/internal/v1/" + route,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code)
        return reply.content, reply.headers["X-HR-Signature"]

    for name, target in targets.items():
        setattr(target.app.state, name + "_signatures", signatures[name])
        if name != "privacy":
            for attr, cls in (
                ("market_access", MarketAccess),
                ("processing_access", ProcessingAccess),
            ):
                access = cls(target.app.state.settings)
                access._signatures, access._send = signatures[name], send
                setattr(target.app.state, attr, access)
    s = SimpleNamespace(**targets, candidate_id=uuid4(), now=datetime.now(UTC))
    s.auth = token(s.candidate_id)
    reply = s.candidate.client.post(
        "/v1/candidates/me",
        json=dict(
            display_name="Candidate",
            specialization="backend",
            declared_grade="junior",
            additional_specializations=[dict(specialization="security", declared_grade="middle")],
        ),
        headers=headers(s.auth, "profile"),
    )
    assert reply.status_code == 201, reply.text
    reply = s.privacy.client.post(
        "/v1/consents",
        json=dict(purpose="task_recommendations", document_version="demo-v1"),
        headers=headers(s.auth, "consent"),
    )
    assert reply.status_code == 201, reply.text
    s.consent = reply.json()["consent_id"]
    s.request = SimpleNamespace(app=s.candidate.app, state=SimpleNamespace(trace_id=uuid4()))
    return s


def offer(
    s,
    specialization="backend",
    grade="junior",
    tags=("python",),
    status="published",
    organization=None,
):
    version = str(uuid4())
    with Session(s.assessment.app.state.engine) as db, db.begin():
        db.add(
            GenerationReference(
                version_id=version,
                reference_id=str(uuid4()),
                number=1,
                organization_id=organization,
                author_id=str(uuid4()),
                data=dict(
                    name="Original task",
                    specialization=specialization,
                    grade=grade,
                    stack_tags=list(tags),
                    format="voice",
                ),
                digest="a" * 64,
                status=status,
                version=1,
                created_at=s.now,
            )
        )
        db.add(
            GenerationJob(
                generation_id=str(uuid4()),
                version_id=version,
                author_id=str(uuid4()),
                specification={},
                specification_digest="a" * 64,
                model="synthetic",
                configuration={},
                prompt_digest="b" * 64,
                status="ready",
                attempts=1,
                created_at=s.now,
                available_at=s.now,
            )
        )
    return version


def subscribe(s, enabled=True, version=0, key="subscription"):
    reply = s.candidate.client.put(
        "/v1/candidates/me/task-subscription",
        json=dict(
            enabled=enabled,
            consent_id=s.consent if enabled else None,
            declared_skills=["python"],
            interval_hours=1,
        ),
        headers=headers(s.auth, key) | {"If-Match": f'"{version}"'},
    )
    assert reply.status_code == 200, reply.text
    return reply.json()


def events(s):
    with Session(s.candidate.app.state.engine) as db:
        return [
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "candidate.task_notification_requested.v1"
        ]


def test_opt_in_matching_all_directions_frequency_dedup_and_notifications(setup):
    s = setup
    offer(s, tags=("python",))
    offer(s, specialization="security", grade="middle", tags=())
    offer(s, tags=("java",))
    offer(s, grade="lead")
    offer(s, status="draft")
    offer(s, organization=str(uuid4()))
    assert not run_one(s.request)
    subscribe(s)
    assert run_one(s.request, now=s.now + timedelta(minutes=1))
    assert len(events(s)) == 1
    assert not run_one(s.request, now=s.now + timedelta(minutes=2))
    # Pages and clock ticks discover both active directions; private tasks remain hidden.
    for hour in range(1, 12):
        run_one(s.request, now=s.now + timedelta(hours=hour, minutes=1))
    assert len(events(s)) == 2
    for event in events(s):
        for _ in range(2):
            with Session(s.notification.app.state.engine) as db, db.begin():
                process_task_notice(db, event, s.notification.app.state.market_access)
    with Session(s.notification.app.state.engine) as db:
        assert len(list(db.scalars(select(NotificationRow)))) == 2
    assert (
        s.notification.client.get("/v1/notifications", headers=s.auth).json() == []
    )  # marketing opt-in
    pref = s.notification.client.put(
        "/v1/notifications/preferences",
        json=dict(in_app=True, marketing_in_app=True),
        headers=headers(s.auth, "preferences", 1),
    )
    assert pref.status_code == 200, pref.text
    result = s.notification.client.get("/v1/notifications", headers=s.auth)
    assert result.status_code == 200 and len(result.json()) == 2, result.text
    subscribe(s, False, 1, "cancel")
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []
    assert (
        s.candidate.client.get("/v1/candidates/me/task-recommendations", headers=s.auth).json()[
            "items"
        ]
        == []
    )
    subscribe(s, True, 2, "again")
    for hour in range(12, 18):
        run_one(s.request, now=s.now + timedelta(hours=hour))
    assert len(events(s)) == 2


def test_revocation_unpublication_profile_change_and_privacy_delete(setup):
    s = setup
    version = offer(s)
    subscribe(s)
    assert run_one(s.request, now=s.now + timedelta(minutes=1))
    route = "/v1/candidates/me/task-recommendations"
    assert len(s.candidate.client.get(route, headers=s.auth).json()["items"]) == 1
    with Session(s.assessment.app.state.engine) as db, db.begin():
        db.get(GenerationReference, version).status = "archived"
    assert s.candidate.client.get(route, headers=s.auth).json()["items"] == []
    with Session(s.assessment.app.state.engine) as db, db.begin():
        db.get(GenerationReference, version).status = "published"
    with Session(s.candidate.app.state.engine) as db, db.begin():
        db.get(CandidateProfile, str(s.candidate_id)).declared_grade = "lead"
    assert s.candidate.client.get(route, headers=s.auth).json()["items"] == []
    reply = s.privacy.client.post(
        f"/v1/consents/{s.consent}/revoke", headers=headers(s.auth, "revoke", 1)
    )
    assert reply.status_code == 200, reply.text
    assert run_one(s.request, now=s.now + timedelta(hours=2))
    assert not s.candidate.client.get("/v1/candidates/me/task-subscription", headers=s.auth).json()[
        "enabled"
    ]
    request_id = uuid4()
    event = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        aggregate_id=request_id,
        aggregate_version=1,
        correlation_id=uuid4(),
        payload={"candidate_id": s.candidate_id, "request_id": request_id},
    )
    with Session(s.candidate.app.state.engine) as db, db.begin():
        process_deletion_request(db, event)
    with Session(s.candidate.app.state.engine) as db:
        assert db.get(TaskSubscription, str(s.candidate_id)) is None
        assert db.scalar(select(TaskRecommendation)) is None
    assert not run_one(s.request, now=s.now + timedelta(days=1))


def test_cancellation_during_catalog_fetch_cannot_enqueue_stale_notice(setup):
    s = setup
    offer(s)
    subscribe(s)
    market = s.candidate.app.state.market_access
    original = market._send
    cancelled = False

    def during_fetch(route, *args, **kwargs):
        nonlocal cancelled
        response = original(route, *args, **kwargs)
        if route == "market/task-catalog" and not cancelled:
            cancelled = True
            subscribe(s, False, 1, "cancel-in-flight")
        return response

    market._send = during_fetch
    assert run_one(s.request, now=s.now + timedelta(minutes=1))
    assert cancelled and events(s) == []


def test_late_notification_after_privacy_deletion_is_acknowledged_without_resurrection(setup):
    s = setup
    offer(s)
    subscribe(s)
    assert run_one(s.request, now=s.now + timedelta(minutes=1))
    notice_event = events(s)[0]
    request_id = uuid4()
    event = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        aggregate_id=request_id,
        aggregate_version=1,
        correlation_id=uuid4(),
        payload={"candidate_id": s.candidate_id, "request_id": request_id},
    )
    with Session(s.candidate.app.state.engine) as db, db.begin():
        process_deletion_request(db, event)
    with Session(s.notification.app.state.engine) as db, db.begin():
        assert process_task_notice(db, notice_event, s.notification.app.state.market_access)
    with Session(s.notification.app.state.engine) as db:
        assert db.scalar(select(NotificationRow)) is None
