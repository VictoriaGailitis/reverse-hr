"""Migrated owners, actual signed RPC, real worker delivery and synthetic external systems."""

from datetime import UTC, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_code_runner import deletion
from test_event_transport import signatures as signatures
from test_matching_hiring import consent, invite, matches
from test_matching_hiring import setup as market_setup

from reverse_hr.db import Outbox
from reverse_hr.domains.achievements import (
    AchievementHistory,
    AchievementRow,
    Connection,
    ImportJob,
    run_import,
)
from reverse_hr.domains.achievements import process_deletion_request as delete_achievements
from reverse_hr.domains.demo_ats import ATSCallback, ATSCandidate, ATSDelivery, run_callback
from reverse_hr.domains.integration import Job, process_consent_revoked, run_one
from reverse_hr.domains.integration import process_deletion_request as delete_integration
from reverse_hr.domains.privacy import process_accepted_invitation
from reverse_hr.events import EventEnvelope
from reverse_hr.exchange import ExchangeAccess, ExchangeRequest, context
from reverse_hr.market_access import MarketAccess
from reverse_hr.processing_access import ProcessingAccess, canonical, sign


@pytest.fixture
def setup(service, token, signatures):
    s = market_setup.__wrapped__(service, token, signatures)
    targets = {
        name: getattr(s, name)
        for name in ("privacy", "candidate", "employer", "hiring", "matching")
    }
    for name in ("achievements", "integration", "demo-fsp", "demo-codenrock", "demo-ats"):
        targets[name] = service(name)
        setattr(s, name.replace("-", "_"), targets[name])

    def sender(route, raw, signature, *, origin=None, **kwargs):
        name = origin.split("//")[1].split(":")[0] if origin else "privacy"
        response = targets[name].client.post(
            "/internal/v1/" + route,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise HTTPException(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    for name, target in targets.items():
        target.app.state.exchange_signatures = signatures[name]
        if hasattr(target.app.state, "processing_access"):
            processing = ProcessingAccess(target.app.state.settings)
            processing._signatures, processing._send = signatures[name], sender
            target.app.state.processing_access = processing
        if hasattr(target.app.state, "market_access"):
            market = MarketAccess(target.app.state.settings)
            market._signatures, market._send = signatures[name], sender
            target.app.state.market_access = market
        if hasattr(target.app.state, "exchange_access"):
            exchange = ExchangeAccess(target.app.state.settings)
            exchange._signatures, exchange._send = signatures[name], sender
            target.app.state.exchange_access = exchange
    s.targets, s.sender = targets, sender
    s.admin = token(uuid4(), ("integration_admin",), amr=["mfa"])
    s.ach_mod = token(uuid4(), ("achievement_moderator",), amr=["mfa"])
    s.import_consent = consent(s, "achievement_import")
    s.publication_consent = consent(s, "achievement_publication")
    s.sources = {
        row["adapter"]: row for row in s.achievements.client.get("/v1/achievement-sources").json()
    }
    return s


def request_for(target):
    return SimpleNamespace(app=target.app, state=SimpleNamespace(trace_id=uuid4()))


def connect(s, adapter="demo-fsp"):
    reply = s.achievements.client.post(
        "/v1/achievement-connections",
        json={"source_id": s.sources[adapter]["source_id"], "consent_id": s.import_consent},
        headers=headers(s.auth, str(uuid4())),
    )
    assert reply.status_code == 201, reply.text
    return reply.json()


def synchronize(s, connection):
    reply = s.integration.client.post(
        "/v1/integrations/syncs",
        json={"connection_id": connection["connection_id"]},
        headers=headers(s.auth, str(uuid4())),
    )
    assert reply.status_code == 202, reply.text
    assert run_one(request_for(s.integration))
    return s.integration.client.get(
        "/v1/integrations/jobs/" + reply.json()["job_id"], headers=s.auth
    ).json()


def rows(s):
    return s.achievements.client.get("/v1/achievements/me", headers=s.auth).json()


def publish(s, row):
    response = s.achievements.client.put(
        "/v1/achievements/" + row["achievement_id"] + "/visibility",
        json={"published": True, "consent_id": s.publication_consent},
        headers=headers(s.auth, str(uuid4()), row["version"]),
    )
    assert response.status_code == 200, response.text
    return response.json()


def export_setup(s):
    assert (
        s.candidate.client.put(
            "/v1/candidates/me/contacts",
            json={"email": "candidate@example.test", "phone": "+79991234567"},
            headers=headers(s.auth, "ats-contacts"),
        ).status_code
        == 200
    )
    invitation = invite(s).json()["invitation_id"]
    disclosure = consent(s, "contact_disclosure")
    response = s.hiring.client.post(
        "/v1/invitations/" + invitation + "/accept",
        json={"disclosure_consent_id": disclosure},
        headers=headers(s.auth, "accept-for-ats", 1),
    )
    assert response.status_code == 200, response.text
    with Session(s.hiring.app.state.engine) as db:
        message = next(
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "hiring.invitation_accepted.v1"
        )
    with Session(s.privacy.app.state.engine) as db, db.begin():
        process_accepted_invitation(db, message)
    s.ats_consent = consent(s, "ats_export")
    body = {
        "candidate_id": str(s.candidate_id),
        "organization_id": s.organization_id,
        "invitation_id": invitation,
        "consent_id": s.ats_consent,
    }
    response = s.integration.client.post(
        "/v1/integrations/ats-exports", json=body, headers=headers(s.employer_auth, "export")
    )
    assert response.status_code == 202, response.text
    return body, response.json()


def test_demo_sources_import_dedup_visibility_and_matching(setup):
    s = setup
    binding = connect(s)
    result = synchronize(s, binding)
    assert result["status"] == "completed", result
    assert len(rows(s)) == 1
    row = rows(s)[0]
    assert row["demo"] and row["status"] == "confirmed" and not row["published"]
    s.matching.app.state.settings.matching_achievements_enabled = True
    assert matches(s).json()["matches"][0]["achievement_bonus"] == 0
    publish(s, row)
    result = matches(s).json()
    assert result["matches"][0]["achievement_bonus"] == 2
    assert result["matches"][0]["confirmed_grade"] == "middle"
    assert matches(s, "production").json()["matches"] == []
    # A saved match cannot retain withdrawn achievement evidence.
    with Session(s.achievements.app.state.engine) as db, db.begin():
        db.get(Connection, binding["connection_id"]).status = "disconnected"
    assert (
        s.matching.client.get(
            "/v1/matches/" + result["snapshot_id"], headers=s.employer_auth
        ).json()["matches"]
        == []
    )


@pytest.mark.parametrize(
    "scenario,status,count",
    [
        ("empty", "completed", 0),
        ("unavailable", "pending", 0),
        ("updated", "completed", 1),
        ("revoked", "completed", 1),
    ],
)
def test_demo_source_scenarios(setup, scenario, status, count):
    s = setup
    s.demo_codenrock.app.state.settings.demo_source_scenario = scenario
    result = synchronize(s, connect(s, "demo-codenrock"))
    assert result["status"] == status, result
    assert len(rows(s)) == count
    if scenario == "revoked":
        assert rows(s)[0]["status"] == "revoked"


def test_partner_binding_scopes_versions_and_partial_import(setup):
    s = setup
    s.achievements.app.state.settings.deployment_mode = "production"
    partner_id = uuid4()
    auth = s.token(partner_id, ("achievement_partner",))
    source = s.achievements.client.post(
        "/v1/achievement-sources",
        json={
            "key": "partner-test",
            "name": "Synthetic partner",
            "adapter": "partner",
            "partner_id": str(partner_id),
        },
        headers=headers(s.admin, "source"),
    )
    assert source.status_code == 201, source.text
    s.sources["partner"] = source.json()
    pending = connect(s, "partner")
    assert pending["status"] == "pending" and pending["external_account"] is None
    confirmed = s.achievements.client.post(
        "/v1/achievement-link-confirmations",
        json={"connection_id": pending["connection_id"], "external_account": "verified-account"},
        headers=headers(auth, "confirm-link", 1),
    )
    assert confirmed.status_code == 200, confirmed.text
    record = dict(
        external_id="result-1",
        external_account="verified-account",
        external_version=1,
        event="Synthetic partner event",
        discipline="Programming",
        occurred_on="2026-01-01",
        specialization="backend",
        format="team",
        place=None,
        points=60,
        group_size=5,
        evidence_url=None,
        revoked=False,
    )
    path = "/v1/achievements/result-1"
    reply = s.achievements.client.put(path, json=record, headers=headers(auth, "put"))
    assert reply.status_code == 200, reply.text
    assert (
        s.achievements.client.put(path, json=record, headers=headers(auth, "dedup")).json()[
            "status"
        ]
        == "duplicate"
    )
    assert (
        s.achievements.client.put(
            path, json=record | {"points": 61}, headers=headers(auth, "conflict")
        ).status_code
        == 409
    )
    assert (
        s.achievements.client.put(
            path,
            json=record | {"external_version": 2, "points": 61},
            headers=headers(auth, "update"),
        ).status_code
        == 200
    )
    assert (
        s.achievements.client.put(path, json=record, headers=headers(auth, "stale")).json()[
            "status"
        ]
        == "stale"
    )
    assert rows(s)[0]["status"] == "imported_pending" and not rows(s)[0]["demo"]
    batch = s.achievements.client.post(
        "/v1/achievement-imports",
        json={
            "records": [
                record,
                record | {"external_id": "unbound", "external_account": "other-account"},
            ]
        },
        headers=headers(auth, "batch"),
    )
    assert batch.status_code == 202, batch.text
    assert run_import(request_for(s.achievements))
    status = s.achievements.client.get(
        "/v1/achievement-imports/" + batch.json()["import_id"], headers=auth
    ).json()
    assert status["status"] == "partial_failure"
    assert {item["status"] for item in status["results"]} == {"stale", "error"}
    row = rows(s)[0]
    review_path = "/v1/achievements/" + row["achievement_id"] + "/review"
    assert s.achievements.client.get(review_path, headers=s.auth).status_code == 403
    evidence = s.achievements.client.get(review_path, headers=s.ach_mod)
    assert evidence.status_code == 200 and evidence.json()["result"]["external_version"] == 2
    review = s.achievements.client.post(
        "/v1/achievements/" + row["achievement_id"] + "/review",
        json={"status": "confirmed", "reason": "Independent checked source evidence"},
        headers=headers(s.ach_mod, "review", row["version"]),
    )
    assert review.status_code == 200, review.text
    publish(s, review.json())
    s.matching.app.state.settings.matching_achievements_enabled = True
    assert (
        matches(s).json()["matches"][0]["achievement_bonus"] == 0
    )  # team placement is not individual contribution
    access = s.matching.app.state.exchange_access
    assert (
        len(
            access.call("achievements", "summary", s.candidate_id, uuid4(), mode="demo")[
                "achievements"
            ]
        )
        == 1
    )
    with Session(s.achievements.app.state.engine) as db:
        reviewer_id = db.scalar(
            select(AchievementHistory).where(
                AchievementHistory.achievement_id == row["achievement_id"],
                AchievementHistory.action == "human_review",
            )
        ).actor_id
    with Session(s.achievements.app.state.engine) as db, db.begin():
        assert delete_achievements(db, deletion(UUID(reviewer_id)))
    assert (
        access.call("achievements", "summary", s.candidate_id, uuid4(), mode="demo")["achievements"]
        == []
    )
    other = s.token(uuid4(), ("achievement_partner",))
    assert (
        s.achievements.client.put(
            path, json=record, headers=headers(other, "cross-source")
        ).status_code
        == 409
    )
    revoked = s.achievements.client.post(
        path + "/revoke",
        json={"external_version": 3, "reason": "Source withdrew the evidence"},
        headers=headers(auth, "partner-revoke"),
    )
    assert revoked.status_code == 200, revoked.text
    row = rows(s)[0]
    assert row["status"] == "revoked" and not row["published"]
    assert (
        s.achievements.client.post(
            review_path,
            json={"status": "confirmed", "reason": "Cannot override source revocation"},
            headers=headers(s.ach_mod, "reject-reconfirmation", row["version"]),
        ).status_code
        == 409
    )


def test_ats_real_delivery_callbacks_dedup_and_revocation(setup):
    s = setup
    body, job = export_setup(s)
    repeat = s.integration.client.post(
        "/v1/integrations/ats-exports", json=body, headers=headers(s.employer_auth, "export")
    )
    assert repeat.json()["job_id"] == job["job_id"]
    assert run_one(request_for(s.integration))
    delivered = s.integration.client.get(
        "/v1/integrations/jobs/" + job["job_id"], headers=s.employer_auth
    ).json()
    assert delivered["status"] == "completed", delivered
    eid = delivered["external_id"]
    response = s.demo_ats.client.get("/v1/ats/candidates/" + eid, headers=s.employer_auth)
    assert response.status_code == 200, response.text
    assert response.json()["contacts"]["email"] == "candidate@example.test"
    assert run_callback(request_for(s.demo_ats))
    assert (
        s.integration.client.get(
            "/v1/integrations/jobs/" + job["job_id"], headers=s.employer_auth
        ).json()["external_status"]
        == "received"
    )
    status = s.demo_ats.client.post(
        "/v1/ats/candidates/" + eid + "/status",
        json={"status": "interview"},
        headers=headers(s.employer_auth, "ats-interview", response.json()["version"]),
    )
    assert status.status_code == 200, status.text
    assert run_callback(request_for(s.demo_ats))
    assert (
        s.integration.client.get(
            "/v1/integrations/jobs/" + job["job_id"], headers=s.employer_auth
        ).json()["external_status"]
        == "interview"
    )
    # An independently retried stale callback cannot roll the status back.
    access = s.demo_ats.app.state.exchange_access
    assert (
        access.call(
            "integration",
            "status",
            s.candidate_id,
            UUID(job["job_id"]),
            external_id=eid,
            status="received",
            sequence=1,
            organization_id=s.organization_id,
        )["status"]
        == "duplicate"
    )
    assert (
        s.privacy.client.post(
            "/v1/consents/" + s.ats_consent + "/revoke", headers=headers(s.auth, "revoke-ats", 1)
        ).status_code
        == 200
    )
    assert (
        s.demo_ats.client.get("/v1/ats/candidates/" + eid, headers=s.employer_auth).status_code
        == 409
    )
    with Session(s.privacy.app.state.engine) as db:
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "privacy.consent_revoked.v1"
            and row.envelope["payload"]["consent_id"] == s.ats_consent
        )
    with Session(s.integration.app.state.engine) as db, db.begin():
        process_consent_revoked(db, event, request_for(s.integration))
    with Session(s.demo_ats.app.state.engine) as db:
        assert not list(db.scalars(select(ATSCandidate)))


def test_privacy_deletes_achievements_and_downstream_ats_and_blocks_replay(setup):
    s = setup
    synchronize(s, connect(s))
    body, job = export_setup(s)
    assert run_one(request_for(s.integration))
    with Session(s.integration.app.state.engine) as db:
        assert db.get(Job, job["job_id"]).status == "completed"
    event = deletion(s.candidate_id)
    with Session(s.integration.app.state.engine) as db, db.begin():
        assert delete_integration(db, event, request_for(s.integration))
    with Session(s.achievements.app.state.engine) as db, db.begin():
        assert delete_achievements(db, event)
    for target, models in [
        (s.achievements, (AchievementRow, Connection, AchievementHistory, ImportJob)),
        (s.demo_ats, (ATSCandidate, ATSDelivery, ATSCallback)),
        (s.integration, (Job,)),
    ]:
        with Session(target.app.state.engine) as db:
            assert all(not list(db.scalars(select(model))) for model in models)
    assert s.achievements.client.get("/v1/achievements/me", headers=s.auth).status_code == 409
    assert (
        s.integration.client.post(
            "/v1/integrations/ats-exports", json=body, headers=headers(s.employer_auth, "export")
        ).status_code
        == 409
    )


def test_signed_exchange_replay_cross_identity_and_demo_separation(setup):
    s = setup
    request = ExchangeRequest(
        requester="integration",
        operation="pull",
        request_id=uuid4(),
        candidate_id=s.candidate_id,
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
        payload={"external_account": str(s.candidate_id)},
    )
    signed = sign(s.signatures["integration"], context("demo-fsp", "pull", "request"), request)
    args = dict(
        content=canonical(request),
        headers={"Content-Type": "application/json", "X-HR-Signature": signed},
    )
    assert s.demo_fsp.client.post("/internal/v1/exchange/pull", **args).status_code == 200
    assert s.demo_fsp.client.post("/internal/v1/exchange/pull", **args).status_code == 409
    assert s.demo_codenrock.client.post("/internal/v1/exchange/pull", **args).status_code == 401
    s.integration.app.state.settings.deployment_mode = "production"
    assert (
        s.integration.client.post(
            "/v1/integrations/syncs",
            json={"connection_id": uuid4().hex},
            headers=headers(s.auth, "production-demo-denied"),
        ).status_code
        == 409
    )


def test_declared_achievement_never_implies_confirmation_or_grade(setup):
    s = setup
    payload = dict(
        consent_id=s.import_consent,
        event="Candidate statement",
        discipline="Programming",
        occurred_on="2026-01-01",
        specialization="backend",
        format="individual",
    )
    response = s.achievements.client.post(
        "/v1/achievements/declared", json=payload, headers=headers(s.auth, "declare")
    )
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["status"] == "declared" and row["result"]["points"] is None
    assert (
        s.achievements.client.post(
            "/v1/achievements/declared",
            json=payload | {"demo": False},
            headers=headers(s.auth, "spoof-mode"),
        ).status_code
        == 422
    )
    publish(s, row)
    s.matching.app.state.settings.matching_achievements_enabled = True
    assert matches(s).json()["matches"][0]["achievement_bonus"] == 0
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["confirmed_grade"]
        == "middle"
    )


def test_two_connection_commands_and_two_workers_do_not_duplicate(setup):
    from concurrent.futures import ThreadPoolExecutor

    s = setup
    body = {"source_id": s.sources["demo-fsp"]["source_id"], "consent_id": s.import_consent}
    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(
            pool.map(
                lambda key: s.achievements.client.post(
                    "/v1/achievement-connections", json=body, headers=headers(s.auth, key)
                ),
                ["race-a", "race-b"],
            )
        )
    assert sorted(response.status_code for response in responses) == [201, 409]
    binding = next(response.json() for response in responses if response.status_code == 201)
    response = s.integration.client.post(
        "/v1/integrations/syncs",
        json={"connection_id": binding["connection_id"]},
        headers=headers(s.auth, "one-sync"),
    )
    assert response.status_code == 202, response.text
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda _: run_one(request_for(s.integration)), range(2)))
    assert len(rows(s)) == 1


def test_sync_retries_are_bounded_and_consent_revocation_cancels(setup):
    from datetime import timedelta

    s = setup
    s.demo_fsp.app.state.settings.demo_source_scenario = "unavailable"
    binding = connect(s)
    initial = synchronize(s, binding)
    for _ in range(2):
        with Session(s.integration.app.state.engine) as db, db.begin():
            db.get(Job, initial["job_id"]).available_at = datetime.now(UTC) - timedelta(seconds=1)
        assert run_one(request_for(s.integration))
    result = s.integration.client.get(
        "/v1/integrations/jobs/" + initial["job_id"], headers=s.auth
    ).json()
    assert result["status"] == "failed" and result["attempts"] == 3
    assert not run_one(request_for(s.integration))
    assert (
        s.privacy.client.post(
            "/v1/consents/" + s.import_consent + "/revoke",
            headers=headers(s.auth, "stop-import", 1),
        ).status_code
        == 200
    )
    assert (
        s.integration.client.post(
            "/v1/integrations/syncs",
            json={"connection_id": binding["connection_id"]},
            headers=headers(s.auth, "revoked-sync"),
        ).status_code
        == 409
    )


def test_ats_callback_is_available_in_hiring_and_hidden_after_revoke(setup):
    from reverse_hr.domains.hiring_ats import process_status

    s = setup
    body, job = export_setup(s)
    assert run_one(request_for(s.integration))
    assert run_callback(request_for(s.demo_ats))
    with Session(s.integration.app.state.engine) as db:
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "integration.ats_status_changed.v1"
        )
    with Session(s.hiring.app.state.engine) as db, db.begin():
        assert process_status(db, event, s.hiring.app.state.exchange_access)
        assert not process_status(db, event, s.hiring.app.state.exchange_access)
    path = "/v1/invitations/" + body["invitation_id"] + "/ats-status"
    response = s.hiring.client.get(path, headers=s.employer_auth)
    assert response.status_code == 200 and response.json()[0]["status"] == "received", response.text
    assert (
        s.privacy.client.post(
            "/v1/consents/" + s.ats_consent + "/revoke",
            headers=headers(s.auth, "hide-hiring-ats", 1),
        ).status_code
        == 200
    )
    assert s.hiring.client.get(path, headers=s.employer_auth).json() == []


def test_lost_ats_reply_retries_without_duplicate_candidate(setup):
    from datetime import timedelta

    s = setup
    _, job = export_setup(s)
    access = s.integration.app.state.exchange_access
    original = access._send
    lost = False

    def lose_once(route, *args, **kwargs):
        nonlocal lost
        result = original(route, *args, **kwargs)
        if route == "exchange/push" and not lost:
            lost = True
            raise HTTPException(503)
        return result

    access._send = lose_once
    assert run_one(request_for(s.integration))
    with Session(s.demo_ats.app.state.engine) as db:
        first_id = db.scalar(select(ATSCandidate)).external_id
    with Session(s.integration.app.state.engine) as db, db.begin():
        row = db.get(Job, job["job_id"])
        assert row.status == "pending" and row.attempts == 1
        row.available_at = datetime.now(UTC) - timedelta(seconds=1)
    assert run_one(request_for(s.integration))
    with Session(s.demo_ats.app.state.engine) as db:
        candidates = list(db.scalars(select(ATSCandidate)))
        assert len(candidates) == 1 and candidates[0].external_id == first_id
        assert len(list(db.scalars(select(ATSDelivery)))) == 1
    with Session(s.integration.app.state.engine) as db:
        row = db.get(Job, job["job_id"])
        assert row.status == "completed" and row.attempts == 2
        assert row.external_id == first_id


def test_privacy_ack_waits_for_confirmed_downstream_erasure(setup):
    s = setup
    _, job = export_setup(s)
    assert run_one(request_for(s.integration))
    event = deletion(s.candidate_id)
    access = s.integration.app.state.exchange_access
    original = access._send

    def unavailable(route, *args, **kwargs):
        if route == "exchange/erase":
            raise HTTPException(503)
        return original(route, *args, **kwargs)

    access._send = unavailable
    with pytest.raises(HTTPException) as error:
        with Session(s.integration.app.state.engine) as db, db.begin():
            delete_integration(db, event, request_for(s.integration))
    assert error.value.status_code == 503
    with Session(s.integration.app.state.engine) as db:
        assert db.get(Job, job["job_id"]) is not None
        assert not any(
            row.envelope["event_type"] == "integration.data_deleted.v1"
            for row in db.scalars(select(Outbox))
        )
    access._send = original
    with Session(s.integration.app.state.engine) as db, db.begin():
        assert delete_integration(db, event, request_for(s.integration))
    with Session(s.demo_ats.app.state.engine) as db:
        assert not list(db.scalars(select(ATSCandidate)))


def test_publication_revocation_and_source_pause_remove_matching_evidence(setup):
    s = setup
    synchronize(s, connect(s))
    publish(s, rows(s)[0])
    s.matching.app.state.settings.matching_achievements_enabled = True
    assert matches(s).json()["matches"][0]["achievement_bonus"] == 2
    source = s.sources["demo-fsp"]
    response = s.achievements.client.put(
        "/v1/achievement-sources/" + source["source_id"] + "/enabled",
        json={"enabled": False},
        headers=headers(s.admin, "pause-source", source["version"]),
    )
    assert response.status_code == 200, response.text
    assert matches(s).json()["matches"][0]["achievement_bonus"] == 0

    assert (
        s.achievements.client.put(
            "/v1/achievement-sources/" + source["source_id"] + "/enabled",
            json={"enabled": True},
            headers=headers(s.admin, "resume-source", response.json()["version"]),
        ).status_code
        == 200
    )
    assert (
        s.privacy.client.post(
            "/v1/consents/" + s.publication_consent + "/revoke",
            headers=headers(s.auth, "revoke-achievement-publication", 1),
        ).status_code
        == 200
    )
    assert matches(s).json()["matches"][0]["achievement_bonus"] == 0


def test_mirrored_result_does_not_multiply_bonus_across_sources(setup):
    s = setup
    synchronize(s, connect(s))
    synchronize(s, connect(s, "demo-codenrock"))
    for row in rows(s):
        publish(s, row)
    with Session(s.achievements.app.state.engine) as db, db.begin():
        records = list(db.scalars(select(AchievementRow)))
        same_event = records[0].data["event"]
        records[1].data = records[1].data | {"event": same_event.upper() + "  "}
    s.matching.app.state.settings.matching_achievements_enabled = True
    result = matches(s).json()["matches"][0]
    assert result["achievement_bonus"] == 2 and len(result["achievement_ids"]) == 1


def test_deletion_during_source_pull_cannot_restore_achievement(setup):
    s = setup
    binding = connect(s)
    event = deletion(s.candidate_id)
    access = s.integration.app.state.exchange_access
    original = access._send

    def delete_during_pull(route, *args, **kwargs):
        result = original(route, *args, **kwargs)
        if route == "exchange/pull":
            with Session(s.achievements.app.state.engine) as db, db.begin():
                assert delete_achievements(db, event)
        return result

    access._send = delete_during_pull
    result = synchronize(s, binding)
    assert result["status"] == "cancelled"
    assert result["error_code"] == "permission_revoked"
    with Session(s.achievements.app.state.engine) as db:
        assert not list(db.scalars(select(AchievementRow)))
        assert not list(db.scalars(select(Connection)))
