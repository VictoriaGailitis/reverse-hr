"""Migrated services, signed evidence/decision/notice RPC, independent human commands."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

import reverse_hr.services.evaluation.evaluation_llm as llm
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.migrate import migration_config
from reverse_hr.protocols.confirmed_grade_access import ConfirmedGradeAccess
from reverse_hr.protocols.market_access import MarketAccess
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.services.assessment.domain.assessment_appeals import (
    Appeal,
    AppealAction,
    AppealDecision,
    AppealNotice,
)
from reverse_hr.services.assessment.domain.assessment_grades import (
    CandidateGrade,
    GradeDecision,
    GradePolicy,
    utc,
)
from reverse_hr.services.assessment.domain.assessment_sessions import process_deletion_request
from reverse_hr.services.candidate.domain.candidate_grades import (
    CandidateDecision,
    process_grade_decision,
)
from reverse_hr.services.evaluation.domain.evaluation_review import ReviewCommand
from reverse_hr.services.matching.domain.matching import Projection, process_profile_change
from reverse_hr.services.notification.domain.notification import process_appeal_notice
from reverse_hr.services.privacy.domain.privacy import ConsentRecord
from reverse_hr.shared.db import IdempotencyRecord, Outbox
from reverse_hr.shared.llm_configuration import GatewayConfiguration
from tests.services.assessment.test_assessment_grades import decide, proposal, review
from tests.services.assessment.test_assessment_grades import setup as grade_setup
from tests.services.code_runner.test_code_runner import deletion
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch, request):
    s = grade_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    review(s)
    if getattr(request, "param", None) == "llm":
        assert rereview(s, auth=s.grade_auth, model=True).status_code == 200
    initial = decide(
        s,
        action={"rejected": "reject", "technical_failure": "technical_failure"}.get(
            getattr(request, "param", None), "confirm"
        ),
        evidence=proposal(s)["evidence_digest"],
    )
    assert initial.status_code == 200, initial.text
    s.original_id = initial.json()["decision_id"]
    s.peer_id = uuid4()
    s.peer = token(s.peer_id, ("assessment_reviewer",), amr=["mfa"])
    s.privacy = service("privacy")
    s.candidate_service = service("candidate")
    s.matching = service("matching")
    s.notification = service("notification")
    s.privacy.app.state.privacy_signatures = signatures["privacy"]
    s.assessment.app.state.assessment_signatures = signatures["assessment"]
    with Session(s.privacy.app.state.engine) as db, db.begin():
        db.add(
            ConsentRecord(
                consent_id=s.session_body["assessment_consent_id"],
                candidate_id=str(s.candidate),
                purpose="assessment",
                document_version="demo-v1",
                status="active",
                version=1,
                granted_at=datetime.now(UTC),
            )
        )
    oldsender = s.assessment.app.state.grade_access._send

    def sender(route, raw, signature, *, origin=None, **kwargs):
        owner = origin.split("//")[1].split(":")[0] if origin else "privacy"
        targets = {
            "privacy": s.privacy,
            "assessment": s.assessment,
            "candidate": s.candidate_service,
        }
        if (
            route
            in {
                "confirmed-grade",
                "market/appeal-notice",
                "market/purpose-permission",
                "market/profile",
                "processing-status",
                "assessment-permission",
            }
            or owner == "privacy"
        ):
            response = targets[owner].client.post(
                "/internal/v1/" + route,
                content=raw,
                headers={"Content-Type": "application/json", "X-HR-Signature": signature},
            )
            if response.status_code != 200:
                raise HTTPException(response.status_code)
            return response.content, response.headers["X-HR-Signature"]
        return oldsender(route, raw, signature, origin=origin, **kwargs)

    s.sender = sender
    for name, target in [
        ("assessment", s.assessment),
        ("candidate", s.candidate_service),
        ("matching", s.matching),
        ("notification", s.notification),
    ]:
        processing = ProcessingAccess(target.app.state.settings)
        processing._signatures = signatures[name]
        processing._send = sender
        target.app.state.processing_access = processing
        if name != "assessment":
            market = MarketAccess(target.app.state.settings)
            market._signatures = signatures[name]
            market._send = sender
            target.app.state.market_access = market
        setattr(target.app.state, name + "_signatures", signatures[name])
    s.assessment.app.state.grade_access._send = sender
    s.decisions = ConfirmedGradeAccess(s.candidate_service.app.state.settings)
    s.decisions._signatures = signatures["candidate"]
    s.decisions._send = sender
    profile = s.candidate_service.client.post(
        "/v1/candidates/me",
        json={
            "display_name": "Synthetic Candidate",
            "specialization": s.version["specialization"],
            "declared_grade": "lead",
        },
        headers=headers(s.auth, "profile"),
    )
    assert profile.status_code == 201, profile.text
    publish = s.privacy.client.post(
        "/v1/consents",
        json={"purpose": "profile_publication", "document_version": "demo-v1"},
        headers=headers(s.auth, "publish-permission"),
    ).json()["consent_id"]
    assert (
        s.candidate_service.client.put(
            "/v1/candidates/me/publication",
            json={"published": True, "consent_id": publish, "declared_skills": ["python"]},
            headers=headers(s.auth, "publish", 1),
        ).status_code
        == 200
    )
    deliver_grade(s, events(s, "grade_decision_recorded")[0])
    refresh(s)
    return s


def events(s, kind):
    with Session(s.assessment.app.state.engine) as db:
        return [
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "assessment." + kind + ".v1"
        ]


def deliver_grade(s, event):
    with Session(s.candidate_service.app.state.engine) as db, db.begin():
        return process_grade_decision(db, event, s.decisions)


def refresh(s):
    with Session(s.candidate_service.app.state.engine) as db:
        messages = [
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"].startswith("candidate.profile_")
        ]
    with Session(s.matching.app.state.engine) as db, db.begin():
        process_profile_change(
            db,
            max(messages, key=lambda message: message.aggregate_version),
            s.matching.app.state.market_access,
        )


def submit(s, key="appeal", auth=None):
    return s.assessment.client.post(
        "/v1/assessment-appeals",
        json={"decision_id": s.original_id, "reason": "Please recheck the evidence and scoring"},
        headers=headers(auth or s.auth, key),
    )


def claim(s, row, auth=None, key="claim"):
    return s.assessment.client.post(
        "/v1/assessment-appeals/" + row["appeal_id"] + "/claim",
        headers=headers(auth or s.peer, key, row["version"]),
    )


def rereview(s, points=100, *, auth=None, model=False):
    path = f"/v1/evaluation-reviews/stages/{s.stage_id}"
    auth = auth or s.peer
    workspace = s.evaluation.client.get(path, headers=auth)
    assert workspace.status_code == 200, workspace.text
    body = {
        "reason": "Independent fresh review of pinned signed test evidence",
        "decisions": [
            {
                "criterion_key": "shape",
                "points": points,
                "reason": "Rechecked runner proof",
                **(
                    {"test_proof_digest": workspace.json()["test_proof_digest"]}
                    if points is not None
                    else {}
                ),
            }
        ],
    }
    if model:
        settings = s.evaluation.app.state.settings
        settings.evaluation_llm_enabled = True
        settings.evaluation_llm_model = "synthetic-model-v1"
        settings.evaluation_llm_config = GatewayConfiguration(
            origin="https://llm.invalid",
            max_input_tokens=32768,
            max_output_tokens=2048,
            input_microusd_per_million_tokens=1000000,
            output_microusd_per_million_tokens=2000000,
            stage_budget_microusd=150000,
        )
        reply = s.evaluation.client.post(
            path + "/model-attempts", headers=headers(auth, str(uuid4()))
        )
        assert reply.status_code == 202, reply.text
        model_proposal = ReviewCommand(
            reason="Independent model evidence proposal",
            decisions=[
                {
                    "criterion_key": "shape",
                    "points": None,
                    "reason": "Hidden tests must be checked by a human",
                }
            ],
        )
        assert llm.run_one(
            s.evaluation.app.state.engine,
            s.evaluation.app.state.material_access,
            s.evaluation.app.state.artifact_access,
            s.evaluation.app.state.processing_access,
            SimpleNamespace(
                evaluate=lambda **kw: llm.ModelReply(
                    proposal=model_proposal, input_tokens=12, output_tokens=9, cost_microusd=1
                )
            ),
            timeout_seconds=1,
        )
        body["model_attempt_id"] = reply.json()["attempt_id"]
    response = s.evaluation.client.post(
        path + "/reviews",
        json=body,
        headers=headers(auth, str(uuid4()), workspace.json()["version"]),
    )
    return response


def resolve(s, row, action="uphold", status="confirmed", key="resolve", proof=None):
    if proof is None:
        response = s.assessment.client.get(
            "/v1/assessment-appeals/" + row["appeal_id"] + "/evidence", headers=s.peer
        )
        assert response.status_code == 200, response.text
        proof = response.json()["evidence_digest"]
    return s.assessment.client.post(
        "/v1/assessment-appeals/" + row["appeal_id"] + "/resolve",
        json={
            "action": action,
            "status": status,
            "evidence_digest": proof,
            "reason": "Independent reasoned human decision",
        },
        headers=headers(s.peer, key, row["version"]),
    )


def test_appeal_independent_repeat_review_uphold_and_history(setup):
    s = setup
    response = submit(s)
    assert response.status_code == 201, response.text
    row = response.json()
    assert submit(s).json()["appeal_id"] == row["appeal_id"]
    assert submit(s, "duplicate-new-key").status_code == 409
    assert claim(s, row, auth=s.grade_auth).status_code == 403
    assert (
        s.assessment.client.get("/v1/assessment-appeals/queue", headers=s.peer).json()[0][
            "appeal_id"
        ]
        == row["appeal_id"]
    )
    row = claim(s, row).json()
    assert resolve(s, row).status_code == 409
    assert rereview(s).status_code == 200
    proof = s.assessment.client.get(
        "/v1/assessment-appeals/" + row["appeal_id"] + "/evidence", headers=s.peer
    ).json()
    assert (
        proof["repeated_review_complete"]
        and proof["original"]["stages"][0]["review_id"]
        != proof["current"]["stages"][0]["review_id"]
    )
    response = resolve(s, row)
    assert response.status_code == 200, response.text
    assert response.json()["resolution"]["action"] == "uphold"
    assert resolve(s, row).status_code == 200
    assert resolve(s, row, key="second-resolution").status_code == 409
    history = s.assessment.client.get(
        "/v1/assessment-appeals/" + row["appeal_id"] + "/history", headers=s.auth
    ).json()
    assert [entry["action"] for entry in history] == ["submitted", "review_started", "resolved"]
    with Session(s.assessment.app.state.engine) as db:
        assert db.get(GradeDecision, s.original_id).status == "confirmed"
        assert len(list(db.scalars(select(AppealDecision)))) == 1
    final_event = events(s, "grade_decision_recorded")[-1]
    assert deliver_grade(s, final_event)
    assert not deliver_grade(s, final_event)
    refresh(s)
    with Session(s.matching.app.state.engine) as db:
        assert db.get(Projection, str(s.candidate)).card["confirmed_grade"] == "junior"
    history = s.candidate_service.client.get(
        "/v1/candidates/me/grade-history", headers=s.auth
    ).json()
    assert {entry["decision_revision"] for entry in history} == {1, 2}


def test_hidden_test_points_cannot_be_overridden_and_stale_digest_rejected(setup):
    s = setup
    row = claim(s, submit(s).json()).json()
    assert rereview(s, 0).status_code == 409
    assert rereview(s).status_code == 200
    assert resolve(s, row, proof="0" * 64).status_code == 409
    assert resolve(s, row, action="change", status="rejected").status_code == 409
    assert resolve(s, row).status_code == 200


def test_parallel_submission_claim_and_withdraw_resolution(setup):
    s = setup
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda key: submit(s, key), ["first", "second"]))
    assert sorted(response.status_code for response in replies) == [201, 409]
    row = next(response.json() for response in replies if response.status_code == 201)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replies = list(pool.map(lambda key: claim(s, row, key=key), ["claim-a", "claim-b"]))
    assert sorted(response.status_code for response in replies) == [200, 409]
    row = next(response.json() for response in replies if response.status_code == 200)
    assert rereview(s).status_code == 200
    proof = s.assessment.client.get(
        "/v1/assessment-appeals/" + row["appeal_id"] + "/evidence", headers=s.peer
    ).json()["evidence_digest"]
    with ThreadPoolExecutor(max_workers=2) as pool:
        a = pool.submit(resolve, s, row, proof=proof)
        b = pool.submit(
            s.assessment.client.post,
            "/v1/assessment-appeals/" + row["appeal_id"] + "/withdraw",
            headers=headers(s.auth, "withdraw", row["version"]),
        )
        statuses = [a.result().status_code, b.result().status_code]
    assert sorted(statuses) == [200, 409]


def test_deadline_ownership_mfa_and_overdue_queue(setup, token):
    s = setup
    assert submit(s, auth=token(uuid4())).status_code == 404
    row = submit(s).json()
    assert claim(s, row, auth=token(s.peer_id, ("assessment_reviewer",))).status_code == 403
    with Session(s.assessment.app.state.engine) as db, db.begin():
        db.get(Appeal, row["appeal_id"]).review_due_at = datetime.now(UTC) - timedelta(seconds=1)
    assert s.assessment.client.get("/v1/assessment-appeals/queue", headers=s.peer).json()[0][
        "overdue"
    ]
    assert claim(s, row).status_code == 200
    assert (
        s.assessment.client.get(
            "/v1/assessment-appeals/" + row["appeal_id"], headers=token(uuid4(), ("employer",))
        ).status_code
        == 403
    )


def test_privacy_erases_reasons_evidence_notices_and_reviewer_caches(setup):
    s = setup
    row = claim(s, submit(s).json()).json()
    assert rereview(s).status_code == 200
    assert resolve(s, row).status_code == 200
    for message in events(s, "appeal_notification_requested"):
        with Session(s.notification.app.state.engine) as db, db.begin():
            assert process_appeal_notice(db, message, s.notification.app.state.market_access)
            assert not process_appeal_notice(db, message, s.notification.app.state.market_access)
    assert len(s.notification.client.get("/v1/notifications", headers=s.auth).json()) == 3
    messages = events(s, "appeal_notification_requested")
    with Session(s.assessment.app.state.engine) as db, db.begin():
        process_deletion_request(db, deletion(s.candidate))
    with Session(s.assessment.app.state.engine) as db:
        for model in (Appeal, AppealAction, AppealDecision, AppealNotice):
            assert not list(db.scalars(select(model)))
        assert not list(
            db.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.operation.startswith("appeal_"))
            )
        )
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []
    with Session(s.notification.app.state.engine) as db, db.begin():
        process_appeal_notice(
            db,
            messages[-1].model_copy(update={"event_id": uuid4()}),
            s.notification.app.state.market_access,
        )
    assert (
        s.assessment.client.get(
            "/v1/assessment-appeals/" + row["appeal_id"], headers=s.peer
        ).status_code
        == 404
    )


def test_revoked_processing_and_reviewer_deletion_reassignment(setup, token):
    s = setup
    row = claim(s, submit(s).json()).json()
    with Session(s.assessment.app.state.engine) as db, db.begin():
        process_deletion_request(db, deletion(s.peer_id))
    current = s.assessment.client.get(
        "/v1/assessment-appeals/" + row["appeal_id"], headers=s.auth
    ).json()
    assert current["status"] == "submitted" and current["reviewer_id"] is None
    new = token(uuid4(), ("assessment_reviewer",), amr=["mfa"])
    assert claim(s, current, auth=new, key="reassign").status_code == 200
    assert (
        s.privacy.client.post(
            "/v1/consents/" + s.session_body["assessment_consent_id"] + "/revoke",
            headers=headers(s.auth, "revoke", 1),
        ).status_code
        == 200
    )
    assert (
        s.assessment.client.get(
            "/v1/assessment-appeals/" + row["appeal_id"], headers=s.auth
        ).status_code
        == 409
    )


def test_populated_appeal_migration_cannot_partially_downgrade(setup):
    s = setup
    submit(s)
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.assessment.app.state.settings), "0014_assessment")
    assert s.assessment.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("setup", ["rejected"], indirect=True)
def test_change_rejected_to_confirmed_updates_candidate_and_matching(setup):
    s = setup
    row = claim(s, submit(s).json()).json()
    assert rereview(s).status_code == 200
    response = resolve(s, row, action="change")
    assert response.status_code == 200, response.text
    assert response.json()["resolution"]["status"] == "confirmed"
    assert deliver_grade(s, events(s, "grade_decision_recorded")[-1])
    refresh(s)
    with Session(s.matching.app.state.engine) as db:
        assert db.get(Projection, str(s.candidate)).card["confirmed_grade"] == "junior"
    with Session(s.assessment.app.state.engine) as db:
        assert db.get(GradeDecision, s.original_id).status == "rejected"


def test_revoked_grade_cannot_be_restored_by_delayed_original_event(setup):
    s = setup
    original_event = events(s, "grade_decision_recorded")[0]
    row = claim(s, submit(s).json()).json()
    assert rereview(s, None).status_code == 200
    reply = resolve(s, row, action="change", status="technical_failure")
    assert reply.status_code == 200, reply.text
    correction = events(s, "grade_decision_recorded")[-1]
    assert deliver_grade(s, correction)
    refresh(s)
    with Session(s.matching.app.state.engine) as db:
        assert db.get(Projection, str(s.candidate)).card["confirmed_grade"] is None
    # A correction can also arrive before its original event at a fresh history.
    with Session(s.candidate_service.app.state.engine) as db, db.begin():
        db.execute(delete(CandidateDecision))
    assert deliver_grade(s, correction.model_copy(update={"event_id": uuid4()}))
    assert deliver_grade(s, original_event.model_copy(update={"event_id": uuid4()}))
    refresh(s)
    with Session(s.matching.app.state.engine) as db:
        assert db.get(Projection, str(s.candidate)).card["confirmed_grade"] is None
    history = s.candidate_service.client.get(
        "/v1/candidates/me/grade-history", headers=s.auth
    ).json()
    assert {x["decision_revision"] for x in history} == {1, 2}
    assert (
        s.assessment.client.get(
            f"/v1/assessment-sessions/{s.session_id}/evaluation", headers=s.auth
        ).json()["status"]
        == "technical_failure"
    )


@pytest.mark.parametrize("setup", ["llm"], indirect=True)
def test_appeal_preserves_validated_llm_provenance_and_requires_human_review(setup):
    s = setup
    row = claim(s, submit(s).json()).json()
    assert rereview(s).status_code == 200
    assert resolve(s, row).status_code == 409
    assert rereview(s, model=True).status_code == 200
    response = resolve(s, row)
    assert response.status_code == 200, response.text
    with Session(s.assessment.app.state.engine) as db:
        final = db.scalar(select(AppealDecision))
        assert final.evidence["stages"][0]["model_attempt_id"] is not None
        assert final.reviewer_id == str(s.peer_id)


def test_filing_deadline_is_enforced(setup):
    s = setup
    with Session(s.assessment.app.state.engine) as db, db.begin():
        db.get(GradeDecision, s.original_id).created_at = datetime.now(UTC) - timedelta(days=31)
    assert submit(s).status_code == 409
    with Session(s.assessment.app.state.engine) as db:
        assert not list(db.scalars(select(Appeal)))


def test_privacy_deletion_during_evidence_fetch_cannot_finish_appeal(setup, monkeypatch):
    s = setup
    row = claim(s, submit(s).json()).json()
    assert rereview(s).status_code == 200
    access = s.assessment.app.state.grade_access
    fetch = access.fetch

    def delete_after_fetch(**kwargs):
        verified = fetch(**kwargs)
        with Session(s.assessment.app.state.engine) as db, db.begin():
            process_deletion_request(db, deletion(s.candidate))
        return verified

    monkeypatch.setattr(access, "fetch", delete_after_fetch)
    response = s.assessment.client.get(
        "/v1/assessment-appeals/" + row["appeal_id"] + "/evidence", headers=s.peer
    )
    assert response.status_code == 409
    with Session(s.assessment.app.state.engine) as db:
        assert not list(db.scalars(select(AppealDecision)))


def test_appeal_notices_follow_service_preferences_and_live_consent(setup):
    s = setup
    submit(s)
    message = events(s, "appeal_notification_requested")[0]
    with Session(s.notification.app.state.engine) as db, db.begin():
        process_appeal_notice(db, message, s.notification.app.state.market_access)
    assert (
        s.notification.client.get("/v1/notifications", headers=s.auth).json()[0]["category"]
        == "service"
    )
    response = s.notification.client.put(
        "/v1/notifications/preferences",
        json={"in_app": False, "marketing_in_app": True},
        headers=headers(s.auth, "disable-notices", 1),
    )
    assert response.status_code == 200, response.text
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []
    response = s.notification.client.put(
        "/v1/notifications/preferences",
        json={"in_app": True, "marketing_in_app": False},
        headers=headers(s.auth, "enable-notices", 2),
    )
    assert response.status_code == 200, response.text
    assert len(s.notification.client.get("/v1/notifications", headers=s.auth).json()) == 1
    assert (
        s.privacy.client.post(
            "/v1/consents/" + s.session_body["assessment_consent_id"] + "/revoke",
            headers=headers(s.auth, "revoke-notice-access", 1),
        ).status_code
        == 200
    )
    assert s.notification.client.get("/v1/notifications", headers=s.auth).json() == []


@pytest.mark.parametrize("setup", ["technical_failure"], indirect=True)
def test_changed_technical_failure_restores_retry_window_from_original_date(setup):
    s = setup
    row = claim(s, submit(s).json()).json()
    assert rereview(s).status_code == 200
    response = resolve(s, row, action="change")
    assert response.status_code == 200, response.text
    with Session(s.assessment.app.state.engine) as db:
        original = db.get(GradeDecision, s.original_id)
        final = db.scalar(select(AppealDecision))
        policy = db.get(GradePolicy, final.evidence["policy_id"])
        assert utc(final.next_attempt_at) == utc(original.created_at) + timedelta(
            seconds=policy.rules["retry_seconds"]
        )
        grade = db.get(CandidateGrade, (str(s.candidate), original.specialization))
        assert utc(grade.changed_at) == utc(original.created_at)
        assert utc(grade.change_available_at) == utc(original.created_at) + timedelta(
            seconds=policy.rules["grade_change_seconds"]
        )


def test_legacy_grade_history_accepts_duplicate_after_revision_contract_extension(setup):
    s = setup
    with Session(s.candidate_service.app.state.engine) as db, db.begin():
        row = db.get(CandidateDecision, s.original_id)
        row.summary = {
            k: v
            for k, v in row.summary.items()
            if k not in {"decision_revision", "supersedes_decision_id"}
        }
    assert deliver_grade(
        s, events(s, "grade_decision_recorded")[0].model_copy(update={"event_id": uuid4()})
    )
    assert (
        s.candidate_service.client.get("/v1/candidates/me/grade-history", headers=s.auth).json()[0][
            "decision_revision"
        ]
        == 1
    )
