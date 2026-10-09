"""Migrated Assessment API: rotation, immutable variants, privacy and issuance limits."""

import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_assessment_content import PACKAGE, admin
from test_assessment_content import assessment as assessment_fixture
from test_assessment_sessions import make_session, plan
from test_event_transport import signatures as signatures_fixture

from reverse_hr.domains.assessment import ContentPackage
from reverse_hr.domains.assessment_selection import GeneratedVariant, SelectionPolicy
from reverse_hr.domains.assessment_sessions import (
    PracticalSession,
    StageState,
    process_deletion_request,
)
from reverse_hr.events import EventEnvelope
from reverse_hr.migrate import migration_config
from reverse_hr.rights_export import records

assessment = assessment_fixture
signatures = signatures_fixture


def policy(target, token, plans, **limits):
    author, reviewer = admin(token), admin(token)
    body = (
        dict(name="Synthetic rotation", plan_version_ids=[p["plan_version_id"] for p in plans])
        | limits
    )
    created = target.client.post(
        "/v1/assessment-selection-policies", headers=headers(author), json=body
    )
    assert created.status_code == 201, created.text
    key = created.json()["id"]
    published = target.client.post(
        f"/v1/assessment-selection-policies/{key}/publish",
        headers=headers(reviewer, "publish", 1),
        json={"reason": "Reviewed synthetic alternatives"},
    )
    assert published.status_code == 200, published.text
    return key, author


def select_session(target, auth, key, attempt="selected", consent=None):
    body = dict(selection_policy_id=key, assessment_consent_id=str(consent or uuid4()))
    response = target.client.post(
        "/v1/assessment-selected-sessions", headers=headers(auth, attempt), json=body
    )
    return response, body


def cancel(target, auth, created):
    assert (
        target.client.post(
            f"/v1/assessment-sessions/{created['session_id']}/cancel",
            headers=headers(auth, "cancel-" + created["session_id"], 1),
        ).status_code
        == 200
    )


def alternative(target, token, original, content, author, package):
    revision = target.client.post(
        f"/v1/content-families/{content['family_id']}/versions",
        headers=headers(author, "new-variant", 1),
        json=package,
    )
    assert revision.status_code == 201
    revised = revision.json()
    assert (
        target.client.post(
            f"/v1/content-versions/{revised['revision_id']}/publish",
            headers=headers(admin(token), "publish", 1),
            json={"reason": "Reviewed alternative"},
        ).status_code
        == 200
    )
    new_plan = target.client.post(
        "/v1/assessment-plans",
        headers=headers(author, "new-plan"),
        json=dict(
            name="Alternative", reason="Synthetic review", revision_ids=[revised["revision_id"]]
        ),
    )
    assert new_plan.status_code == 201, new_plan.text
    return new_plan.json()


def test_rotation_replay_cancel_exhaustion_direct_bypass_and_history(service, token):
    target = service("assessment")
    a, _, _ = plan(target, token)
    b, _, _ = plan(target, token)
    key, _ = policy(target, token, [a, b])
    candidate = uuid4()
    auth = token(candidate)
    first, body = select_session(target, auth, key)
    assert first.status_code == 201, first.text
    assert first.json()["selection"]["policy_id"] == key
    assert "reference_answer" not in first.text and "rubric" not in first.text
    replay = target.client.post(
        "/v1/assessment-selected-sessions", headers=headers(auth, "selected"), json=body
    )
    assert replay.json() == first.json()
    cancel(target, auth, first.json())
    second, _ = select_session(target, auth, key, "second")
    assert second.status_code == 201
    assert second.json()["plan_version_id"] != first.json()["plan_version_id"]
    cancel(target, auth, second.json())
    assert select_session(target, auth, key, "exhausted")[0].status_code == 409
    direct, _, _ = make_session(target, token, a, candidate, key="bypass")
    assert direct.status_code == 409
    history = target.client.get("/v1/assessment-task-history?limit=1", headers=auth).json()
    assert len(history) == 1
    next_page = target.client.get(
        "/v1/assessment-task-history",
        headers=auth,
        params={"limit": 1, "after": history[0]["session_id"]},
    )
    assert (
        len(next_page.json()) == 1 and next_page.json()[0]["session_id"] != history[0]["session_id"]
    )
    assert target.client.get("/v1/assessment-task-history", headers=token()).json() == []
    assert (
        target.client.get(
            "/v1/assessment-task-history",
            headers=token(),
            params={"after": history[0]["session_id"]},
        ).status_code
        == 404
    )
    assert (
        target.client.get("/v1/assessment-task-history?limit=101", headers=auth).status_code == 422
    )


def test_variant_rotation_within_family_and_cooldown_expiry(service, token):
    target = service("assessment")
    a, content, author = plan(target, token)
    changed = copy.deepcopy(PACKAGE)
    changed["tasks"][0]["instruction"] = "Another reviewed input"
    b = alternative(target, token, a, content, author, changed)
    key, _ = policy(target, token, [a, b], family_cooldown_seconds=0, family_candidate_limit=10)
    auth = token()
    first, _ = select_session(target, auth, key)
    assert first.status_code == 201
    cancel(target, auth, first.json())
    second, _ = select_session(target, auth, key, "second")
    assert second.status_code == 201
    assert first.json()["stages"][0]["revision_id"] != second.json()["stages"][0]["revision_id"]
    cancel(target, auth, second.json())
    assert select_session(target, auth, key, "third")[0].status_code == 409
    with Session(target.app.state.engine) as session, session.begin():
        for row in session.scalars(select(PracticalSession)):
            row.created_at = datetime.now(UTC) - timedelta(days=31)
    assert select_session(target, auth, key, "after-window")[0].status_code == 201


def test_family_cooldown_applies_to_other_revisions(service, token):
    target = service("assessment")
    a, content, author = plan(target, token)
    changed = copy.deepcopy(PACKAGE)
    changed["tasks"][0]["instruction"] = "Second input"
    b = alternative(target, token, a, content, author, changed)
    key, _ = policy(target, token, [a, b], variant_cooldown_seconds=0)
    auth = token()
    first, _ = select_session(target, auth, key)
    assert first.status_code == 201
    cancel(target, auth, first.json())
    assert select_session(target, auth, key, "family-repeat")[0].status_code == 409


@pytest.mark.parametrize("limit", ["candidate_session_limit", "family_candidate_limit"])
def test_candidate_rolling_limits_even_when_cooldowns_disabled(service, token, limit):
    target = service("assessment")
    a, content, author = plan(target, token)
    b = alternative(target, token, a, content, author, copy.deepcopy(PACKAGE))
    key, _ = policy(
        target, token, [a, b], family_cooldown_seconds=0, variant_cooldown_seconds=0, **{limit: 1}
    )
    auth = token()
    first, _ = select_session(target, auth, key)
    assert first.status_code == 201
    cancel(target, auth, first.json())
    assert select_session(target, auth, key, "second")[0].status_code == 409


def test_global_frequency_limit_and_concurrent_direct_admission(assessment, token):
    target = assessment
    a, _, _ = plan(target, token)
    b, _, _ = plan(target, token)
    policy(target, token, [a, b], family_global_limit=1)
    candidates = [uuid4(), uuid4()]
    auths = [token(subject) for subject in candidates]

    def issue(index):
        return target.client.post(
            "/v1/assessment-sessions",
            headers=headers(auths[index], "race"),
            json=dict(plan_version_id=a["plan_version_id"], assessment_consent_id=str(uuid4())),
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(issue, range(2)))
    assert outcomes.count(201) == 1 and all(code in {201, 409, 503} for code in outcomes)
    with Session(target.app.state.engine) as session:
        assert len(list(session.scalars(select(PracticalSession)))) == 1
    assert issue(outcomes.index(201) ^ 1) == 409


def test_retired_alternative_skipped_and_policy_retirement_does_not_rewrite_session(service, token):
    target = service("assessment")
    a, _, author = plan(target, token)
    b, _, _ = plan(target, token)
    key, owner = policy(target, token, [a, b])
    target.client.post(
        f"/v1/assessment-plans/{a['plan_version_id']}/retire",
        headers=headers(author, "retire", 1),
        json={"reason": "Retire"},
    )
    auth = token()
    first, body = select_session(target, auth, key)
    assert first.status_code == 201 and first.json()["plan_version_id"] == b["plan_version_id"]
    assert (
        target.client.post(
            f"/v1/assessment-selection-policies/{key}/retire",
            headers=headers(owner, "retire", 2),
            json={"reason": "Retire"},
        ).status_code
        == 200
    )
    replay = target.client.post(
        "/v1/assessment-selected-sessions", headers=headers(auth, "selected"), json=body
    )
    assert replay.json() == first.json()
    assert select_session(target, token(), key, "new")[0].status_code == 409


def test_policy_review_rights_and_comparability(service, token):
    target = service("assessment")
    a, _, _ = plan(target, token)
    b, _, _ = plan(target, token)
    author = admin(token)
    body = dict(name="Review", plan_version_ids=[a["plan_version_id"], b["plan_version_id"]])
    assert (
        target.client.post(
            "/v1/assessment-selection-policies", headers=headers(token()), json=body
        ).status_code
        == 403
    )
    created = target.client.post(
        "/v1/assessment-selection-policies", headers=headers(author), json=body
    )
    key = created.json()["id"]
    assert (
        target.client.post(
            f"/v1/assessment-selection-policies/{key}/publish",
            headers=headers(author, "self", 1),
            json={"reason": "Self"},
        ).status_code
        == 403
    )
    duplicate = body | {"plan_version_ids": [a["plan_version_id"], a["plan_version_id"]]}
    assert (
        target.client.post(
            "/v1/assessment-selection-policies",
            headers=headers(author, "duplicate"),
            json=duplicate,
        ).status_code
        == 422
    )
    changed = copy.deepcopy(PACKAGE)
    changed["tasks"][0]["duration_seconds"] += 60
    c, _, _ = plan(target, token, changed)
    assert (
        target.client.post(
            "/v1/assessment-selection-policies",
            headers=headers(author, "structure"),
            json=body | {"plan_version_ids": [a["plan_version_id"], c["plan_version_id"]]},
        ).status_code
        == 409
    )
    assert (
        target.client.post(
            "/v1/assessment-selection-policies",
            headers=headers(author, "mapping"),
            json=body | {"grade_policy_ids": {a["plan_version_id"]: str(uuid4())}},
        ).status_code
        == 422
    )


def test_consent_failure_not_swallowed_and_corrupted_selection_snapshot(service, token):
    target = service("assessment")
    a, _, _ = plan(target, token)
    b, _, _ = plan(target, token)
    key, _ = policy(target, token, [a, b])

    def unavailable(*args):
        raise HTTPException(503, "Privacy unavailable")

    target.app.state.processing_access.check_assessment = unavailable
    assert select_session(target, token(), key)[0].status_code == 503
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(PracticalSession)) is None
    target.app.state.processing_access.check_assessment = lambda *_: None
    auth = token()
    first, _ = select_session(target, auth, key)
    with Session(target.app.state.engine) as session, session.begin():
        row = session.get(PracticalSession, first.json()["session_id"])
        row.selection_policy_snapshot = {"tampered": True}
    assert (
        target.client.get(
            f"/v1/assessment-sessions/{first.json()['session_id']}", headers=auth
        ).status_code
        == 409
    )


def test_reviewed_parameter_generation_bounds_dedup_and_publication(service, token):
    target = service("assessment")
    package = copy.deepcopy(PACKAGE)
    package["tasks"][0]["instruction"] = "Synthetic input {{size}} in {{domain}}"
    package["tasks"][0]["reference_answer"] = "Synthetic reference {{size}}"
    _, base, author = plan(target, token, package)
    body = dict(
        base_revision_id=base["revision_id"],
        allowed_parameters={"size": ["10", "20"], "domain": ["orders"]},
    )
    created = target.client.post(
        "/v1/assessment-variant-templates", headers=headers(author), json=body
    )
    assert created.status_code == 201, created.text
    key = created.json()["id"]
    path = f"/v1/assessment-variant-templates/{key}"
    generate_body = dict(parameters={"size": "10", "domain": "orders"}, family_version=1)
    assert (
        target.client.post(
            path + "/generate", headers=headers(author, "draft"), json=generate_body
        ).status_code
        == 409
    )
    assert (
        target.client.post(
            path + "/publish", headers=headers(author, "self", 1), json={"reason": "Self"}
        ).status_code
        == 403
    )
    reviewer = admin(token)
    assert (
        target.client.post(
            path + "/publish",
            headers=headers(reviewer, "review", 1),
            json={"reason": "Reviewed bounded substitutions"},
        ).status_code
        == 200
    )
    assert (
        target.client.post(
            path + "/generate",
            headers=headers(author, "outside"),
            json=generate_body | {"parameters": {"size": "999", "domain": "orders"}},
        ).status_code
        == 422
    )
    generated = target.client.post(
        path + "/generate", headers=headers(author, "generate"), json=generate_body
    )
    assert generated.status_code == 201, generated.text
    assert generated.json()["status"] == "draft"
    task = generated.json()["content"]["tasks"][0]
    assert task["instruction"] == "Synthetic input 10 in orders"
    assert task["reference_answer"] == "Synthetic reference 10"
    assert task["rubric"] == package["tasks"][0]["rubric"]
    assert (
        target.client.post(
            path + "/generate", headers=headers(author, "generate"), json=generate_body
        ).json()
        == generated.json()
    )
    assert (
        target.client.post(
            path + "/generate",
            headers=headers(author, "duplicate"),
            json=generate_body | {"family_version": 2},
        ).status_code
        == 409
    )
    with Session(target.app.state.engine) as session:
        record = session.get(GeneratedVariant, generated.json()["revision_id"])
        assert record.parameters == generate_body["parameters"]
    assert (
        target.client.post(
            f"/v1/content-versions/{generated.json()['revision_id']}/publish",
            headers=headers(author, "self-variant", 1),
            json={"reason": "Self"},
        ).status_code
        == 403
    )
    assert (
        target.client.post(
            f"/v1/content-versions/{generated.json()['revision_id']}/publish",
            headers=headers(reviewer, "review-variant", 1),
            json={"reason": "Review"},
        ).status_code
        == 200
    )


def test_followup_hidden_until_parent_submission_in_api_and_privacy(service, token):
    target = service("assessment")
    package = copy.deepcopy(PACKAGE)
    child = copy.deepcopy(package["tasks"][0])
    child.update(key="followup", follows_task_key="sample", instruction="SECRET new constraint")
    package["tasks"].append(child)
    version, _, _ = plan(target, token, package)
    candidate = uuid4()
    created, auth, _ = make_session(target, token, version, candidate)
    assert created.status_code == 201
    assert "SECRET" not in created.text
    assert created.json()["followups"][0]["available"] is False
    key = created.json()["session_id"]
    with Session(target.app.state.engine) as session:
        exported = list(records(session, "assessment", candidate))
        assert "SECRET" not in str(exported)
    assert (
        target.client.post(
            f"/v1/assessment-sessions/{key}/start", headers=headers(auth, "start", 1)
        ).status_code
        == 200
    )
    # Pin a submitted state; the lifecycle suite separately verifies submission evidence.
    parent = created.json()["stages"][0]["stage_id"]
    with Session(target.app.state.engine) as session, session.begin():
        session.get(StageState, parent).status = "submitted"
    disclosed = target.client.get(f"/v1/assessment-sessions/{key}", headers=auth)
    assert disclosed.json()["stages"][1]["instruction"] == "SECRET new constraint"
    assert disclosed.json()["followups"][0]["available"] is True
    with Session(target.app.state.engine) as session:
        assert "SECRET" in str(list(records(session, "assessment", candidate)))


@pytest.mark.parametrize("parent", ["unknown", "followup"])
def test_followup_cannot_reference_future_or_itself(parent):
    package = copy.deepcopy(PACKAGE)
    package["tasks"][0]["follows_task_key"] = parent
    with pytest.raises(ValueError, match="earlier task"):
        ContentPackage(**package)


def test_privacy_deletes_history_replay_and_downgrade_preserves_readiness(service, token):
    target = service("assessment")
    a, _, _ = plan(target, token)
    b, _, _ = plan(target, token)
    key, _ = policy(target, token, [a, b])
    subject = uuid4()
    auth = token(subject)
    first, body = select_session(target, auth, key)
    assert first.status_code == 201
    with pytest.raises(RuntimeError, match="populated"):
        command.downgrade(migration_config(target.app.state.settings), "0016_assessment")
    assert target.client.get("/health/ready").status_code == 200
    request_id = uuid4()
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    with Session(target.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, event)
        assert (
            session.scalar(
                select(PracticalSession).where(PracticalSession.candidate_id == str(subject))
            )
            is None
        )
        assert session.scalar(select(SelectionPolicy)) is not None
    assert target.client.get("/v1/assessment-task-history", headers=auth).status_code == 409
    assert (
        target.client.post(
            "/v1/assessment-selected-sessions", headers=headers(auth, "selected"), json=body
        ).status_code
        == 409
    )


def test_graded_rotation_pins_each_plans_policy_and_blocks_ungraded_bypass(service, token):
    from test_assessment_grades import calibration

    target = service("assessment")
    plans = [plan(target, token)[0] for _ in range(2)]
    mapping = {}
    for version in plans:
        author, reviewer = admin(token), admin(token)
        created = target.client.post(
            "/v1/grade-policies",
            headers=headers(author),
            json={
                "plan_version_id": version["plan_version_id"],
                "rules": {
                    "weights": {"structure": 100},
                    "minimums": {"structure": 60},
                    "pass_score": 70,
                    "retry_seconds": 3600,
                    "grade_change_seconds": 7776000,
                },
            },
        )
        assert created.status_code == 201, created.text
        key = created.json()["policy_id"]
        approved = target.client.post(
            f"/v1/grade-policies/{key}/approve",
            headers=headers(reviewer, "approve", 1),
            json=calibration(),
        )
        assert approved.status_code == 200, approved.text
        mapping[version["plan_version_id"]] = key
    selection_id, _ = policy(target, token, plans, grade_policy_ids=mapping)
    candidate = uuid4()
    auth = token(candidate)
    first, _ = select_session(target, auth, selection_id)
    assert first.status_code == 201, first.text
    with Session(target.app.state.engine) as session:
        row = session.get(PracticalSession, first.json()["session_id"])
        assert row.grade_policy_id == mapping[row.plan_version_id]
        assert row.grade_policy_digest
    cancel(target, auth, first.json())
    second, _ = select_session(target, auth, selection_id, "second")
    assert second.status_code == 201
    assert second.json()["plan_version_id"] != first.json()["plan_version_id"]
    bypass, _, _ = make_session(target, token, plans[0], uuid4(), "ungraded-bypass")
    assert bypass.status_code == 409


def test_candidate_discovers_offers_but_cannot_read_configuration_and_owner_restriction(
    service, token
):
    target = service("assessment")
    a, _, _ = plan(target, token)
    b, _, _ = plan(target, token)
    owner = uuid4()
    author = admin(token, owner)
    created = target.client.post(
        "/v1/assessment-selection-policies",
        headers=headers(author),
        json={"name": "Offer", "plan_version_ids": [a["plan_version_id"], b["plan_version_id"]]},
    )
    key = created.json()["id"]
    path = f"/v1/assessment-selection-policies/{key}"
    assert (
        target.client.post(
            path + "/publish",
            headers=headers(admin(token), "publish", 1),
            json={"reason": "Review"},
        ).status_code
        == 200
    )
    auth = token()
    offers = target.client.get("/v1/assessment-selection-policies", headers=auth)
    assert offers.status_code == 200 and offers.json()[0]["policy_id"] == key
    assert "plan_version_ids" not in offers.text
    assert target.client.get(path, headers=auth).status_code == 403
    assert target.client.get(path, headers=author).json()["status"] == "published"
    request_id = uuid4()
    event = EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        aggregate_id=request_id,
        aggregate_version=1,
        correlation_id=uuid4(),
        payload={"candidate_id": owner, "request_id": request_id},
    )
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, event)
    assert target.client.get("/v1/assessment-selection-policies", headers=auth).json() == []
    assert select_session(target, auth, key)[0].status_code == 409
    direct, _, _ = make_session(target, token, a, key="restricted-config")
    assert direct.status_code == 409


def test_signed_workspace_access_cannot_open_followup_before_parent_submission(
    service, token, signatures
):
    from reverse_hr.processing_access import canonical, sign
    from reverse_hr.stage_access import STAGE_REQUEST_CONTEXT, StageRequest

    target = service("assessment")
    target.app.state.assessment_signatures = signatures["assessment"]
    package = copy.deepcopy(PACKAGE)
    child = copy.deepcopy(package["tasks"][0])
    child.update(key="followup", follows_task_key="sample", instruction="New constraint")
    package["tasks"].append(child)
    version, _, _ = plan(target, token, package)
    candidate = uuid4()
    created, auth, _ = make_session(target, token, version, candidate)
    data = created.json()

    def permission(purpose):
        body = StageRequest(
            candidate_id=candidate,
            session_id=data["session_id"],
            stage_id=data["stages"][1]["stage_id"],
            requester="coding-workspace",
            purpose=purpose,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        reply = target.client.post(
            "/internal/v1/workspace-stage",
            content=canonical(body),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": sign(signatures["coding-workspace"], STAGE_REQUEST_CONTEXT, body),
            },
        )
        assert reply.status_code == 200
        return reply.json()["allowed"]

    assert not permission("write") and not permission("read")
    assert (
        target.client.post(
            f"/v1/assessment-sessions/{data['session_id']}/start", headers=headers(auth, "start", 1)
        ).status_code
        == 200
    )
    with Session(target.app.state.engine) as session, session.begin():
        session.get(StageState, data["stages"][0]["stage_id"]).status = "submitted"
    assert permission("read")
    assert not permission("write")  # Still requires the follow-up to be the active timed stage.
