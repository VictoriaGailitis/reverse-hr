"""Synthetic suite fixtures only; these tests never execute candidate code."""

import copy
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_assessment_content import PACKAGE, admin

from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.assessment import ContentRevision
from reverse_hr.domains.assessment_sessions import AssessmentSubject, process_deletion_request
from reverse_hr.domains.assessment_tests import TestSuite as SuiteRecord
from reverse_hr.domains.code_runner import Output
from reverse_hr.events import EventEnvelope
from reverse_hr.migrate import migration_config
from reverse_hr.test_suites import SuiteDefinition, compare, validate_captures

SPEC = {
    "format": "code",
    "runtime_contract": "python-3.12-sqlite-demo-v1",
    "comparison_policy": "utf8-exact-v1",
    "cases": [{"key": "one", "criterion_key": "shape", "fixtures": [], "expected_stdout": "ok\n"}],
    "reference": {"files": [{"path": "main.py", "content": "print('ok')"}]},
    "mutants": [
        {
            "key": "wrong",
            "description": "Synthetic wrong output",
            "source": {"files": [{"path": "main.py", "content": "print('wrong')"}]},
        },
        {
            "key": "crash",
            "description": "Synthetic exception",
            "source": {"files": [{"path": "main.py", "content": "raise ValueError()"}]},
        },
    ],
}


@pytest.fixture
def setup(service, token):
    target = service("assessment")
    author_id = uuid4()
    author, reviewer = admin(token, author_id), admin(token)
    package = copy.deepcopy(PACKAGE)
    package["tasks"][0]["reference_answer"] = SPEC["reference"]["files"][0]["content"]
    created = target.client.post(
        "/v1/content-families",
        headers=headers(reviewer, "content"),
        json={"name": "Synthetic", "content": package},
    ).json()
    revision = created["revision_id"]
    assert (
        target.client.post(
            f"/v1/content-versions/{revision}/publish",
            headers=headers(admin(token), "publish", 1),
            json={"reason": "Synthetic review"},
        ).status_code
        == 200
    )
    path = f"/v1/content-versions/{revision}/tasks/sample/test-suites"
    return target, author, reviewer, author_id, revision, path


def create(setup, body=None, key="suite"):
    response = setup[0].client.post(setup[5], headers=headers(setup[1], key), json=body or SPEC)
    assert response.status_code == 201, response.text
    return response.json()


def test_immutable_review_retirement_and_current_replay(setup):
    target, author, reviewer, _, _, _ = setup
    first = create(setup)
    path = f"/v1/test-suites/{first['suite_id']}"
    reason = {"reason": "Synthetic static review"}
    assert (
        target.client.post(
            path + "/review", headers=headers(author, "self", 1), json=reason
        ).status_code
        == 403
    )
    reviewed = target.client.post(
        path + "/review", headers=headers(reviewer, "review", 1), json=reason
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "reviewed"
    assert not reviewed.json()["runtime_validated"] and not reviewed.json()["scoring_enabled"]
    assert (
        target.client.post(
            path + "/retire", headers=headers(reviewer, "stale", 1), json=reason
        ).status_code
        == 409
    )
    assert (
        target.client.post(
            path + "/retire", headers=headers(reviewer, "retire", 2), json=reason
        ).status_code
        == 200
    )
    replay = target.client.post(setup[5], headers=headers(author, "suite"), json=SPEC)
    assert replay.json()["status"] == "retired" and replay.json()["version"] == 3
    changed = copy.deepcopy(SPEC)
    changed["cases"][0]["expected_stdout"] = "changed\n"
    assert (
        target.client.post(setup[5], headers=headers(author, "suite"), json=changed).status_code
        == 409
    )
    second = create(setup, changed, "new-suite")
    assert second["number"] == 2 and second["suite_id"] != first["suite_id"]
    assert target.client.get(path, headers=author).json()["definition"] == first["definition"]
    with Session(target.app.state.engine) as session:
        events = session.scalars(select(Outbox)).all()
        suite_events = [
            row.envelope for row in events if "test_suite" in row.envelope["event_type"]
        ]
        assert len(suite_events) == 4
        assert all(set(item["payload"]) == {"suite_id", "revision_id"} for item in suite_events)


@pytest.mark.parametrize(
    "roles,mfa",
    [
        (("candidate",), True),
        (("employer",), True),
        (("assessment_reviewer",), True),
        (("content_admin",), False),
    ],
)
def test_private_access(setup, token, roles, mfa):
    first = create(setup)
    auth = token(roles=roles, amr=["mfa"] if mfa else [])
    target = setup[0]
    path = f"/v1/test-suites/{first['suite_id']}"
    assert target.client.get(path, headers=auth).status_code == 403
    assert target.client.post(setup[5], headers=headers(auth), json=SPEC).status_code == 403
    for action in ("review", "retire"):
        assert (
            target.client.post(
                path + "/" + action, headers=headers(auth, action, 1), json={"reason": "Attempt"}
            ).status_code
            == 403
        )
    assert target.client.get(path).status_code == 401


@pytest.mark.parametrize(
    "change", ["format", "reference", "criterion", "unknown_task", "draft", "retired"]
)
def test_binding_to_published_task(setup, change):
    target, author, reviewer, _, revision, path = setup
    body = copy.deepcopy(SPEC)
    if change == "format":
        body["format"] = "sql"
        for source in [body["reference"], *(item["source"] for item in body["mutants"])]:
            source["files"][0]["path"] = "query.sql"
    elif change == "reference":
        body["reference"]["files"][0]["content"] = "print('different')"
    elif change == "criterion":
        body["cases"][0]["criterion_key"] = "unknown"
    elif change == "unknown_task":
        path = path.replace("/sample/", "/absent/")
    elif change == "retired":
        assert (
            target.client.post(
                f"/v1/content-versions/{revision}/retire",
                headers=headers(reviewer, "retire-content", 2),
                json={"reason": "Withdrawal"},
            ).status_code
            == 200
        )
    else:
        with Session(target.app.state.engine) as session, session.begin():
            row = session.get(ContentRevision, revision)
            row.status, row.published_at = "draft", None
    assert target.client.post(path, headers=headers(author), json=body).status_code == (
        404 if change == "unknown_task" else 409
    )


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_case",
        "duplicate_mutant",
        "duplicate_source",
        "traversal",
        "collision",
        "input_overwrite",
        "fixture_path",
        "fixture_collision",
        "bytes",
        "too_many_files",
        "client_validated",
        "bad_policy",
    ],
)
def test_invalid_specs_are_rejected(change):
    body = copy.deepcopy(SPEC)
    if change == "duplicate_case":
        body["cases"] *= 2
    elif change == "duplicate_mutant":
        body["mutants"][1]["key"] = "wrong"
    elif change == "duplicate_source":
        body["mutants"][0]["source"] = body["reference"]
    elif change == "traversal":
        body["reference"]["files"].append({"path": "../secret", "content": "x"})
    elif change == "collision":
        body["reference"]["files"].append({"path": "main.py/file", "content": "x"})
    elif change == "input_overwrite":
        body["reference"]["files"].append({"path": "test_inputs/x", "content": "x"})
    elif change == "fixture_path":
        body["cases"][0]["fixtures"] = [{"path": "main.py", "content": "x"}]
    elif change == "fixture_collision":
        body["cases"][0]["fixtures"] = [
            {"path": "test_inputs/x", "content": "x"},
            {"path": "test_inputs/x/y", "content": "x"},
        ]
    elif change == "bytes":
        body["cases"][0]["expected_stdout"] = "я" * 10000
    elif change == "too_many_files":
        body["cases"][0]["fixtures"] = [
            {"path": f"test_inputs/{i}", "content": "x"} for i in range(19)
        ]
        body["reference"]["files"].append({"path": "helper.py", "content": "x"})
    elif change == "client_validated":
        body["runtime_validated"] = True
    else:
        body["comparison_policy"] = "candidate-claims-pass"
    with pytest.raises(ValidationError):
        SuiteDefinition.model_validate(body)


@pytest.mark.parametrize("status", ["technical_error", "cancelled", "limit_exceeded"])
def test_environment_failures_are_inconclusive(status):
    suite = SuiteDefinition.model_validate(SPEC)
    reason = {
        "technical_error": "sandbox_failed",
        "cancelled": "access_withdrawn",
        "limit_exceeded": "time_limit",
    }[status]
    output = Output(status=status, reason=reason)
    assert compare(suite.cases[0], output) == "inconclusive"
    assert (
        validate_captures(
            suite,
            {"one": output},
            {
                item.key: {"one": Output(status="runtime_error", exit_code=1)}
                for item in suite.mutants
            },
        )
        == "inconclusive"
    )


def test_host_comparison_requires_reference_success_and_each_mutant_failure():
    suite = SuiteDefinition.model_validate(SPEC)
    good = Output(status="executed", exit_code=0, stdout="ok\n")
    bad = Output(status="executed", exit_code=0, stdout="ALL TESTS PASSED")
    crash = Output(status="runtime_error", exit_code=1)
    matrix = {"wrong": {"one": bad}, "crash": {"one": crash}}
    assert validate_captures(suite, {"one": good}, matrix) == "accepted"
    assert validate_captures(suite, {"one": bad}, matrix) == "rejected"
    assert validate_captures(suite, {"one": good}, matrix | {"wrong": {"one": good}}) == "rejected"
    assert validate_captures(suite, {}, matrix) == "inconclusive"
    assert (
        validate_captures(suite, {"one": good}, matrix | {"extra": {"one": bad}}) == "inconclusive"
    )
    assert compare(suite.cases[0], good.model_copy(update={"stderr": "warning"})) == "failed"
    assert compare(suite.cases[0], good.model_copy(update={"stdout": "ok"})) == "failed"


@pytest.mark.parametrize("failure", [409, 503])
def test_fresh_permission_closes_cached_replay(setup, failure):
    create(setup)
    target = setup[0]

    def denied(*_):
        raise HTTPException(failure)

    target.app.state.processing_access.check = denied
    assert (
        target.client.post(setup[5], headers=headers(setup[1], "suite"), json=SPEC).status_code
        == failure
    )


def test_author_retention_and_tombstone_blocks_replay(setup):
    first = create(setup)
    target, author, _, subject, _, _ = setup
    request_id = uuid4()
    event = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    with Session(target.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, event)
    with Session(target.app.state.engine) as session:
        assert session.get(AssessmentSubject, str(subject)).status == "restricted"
        assert session.get(SuiteRecord, first["suite_id"]) is not None
        assert not session.scalar(
            select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
        )
    assert (
        target.client.post(setup[5], headers=headers(author, "suite"), json=SPEC).status_code == 409
    )
    assert (
        target.client.get(f"/v1/test-suites/{first['suite_id']}", headers=author).status_code == 409
    )


def test_outbox_failure_rolls_back_suite_and_command(setup, monkeypatch):
    import reverse_hr.domains.assessment_tests as domain

    def fail(*_):
        raise HTTPException(503)

    monkeypatch.setattr(domain, "enqueue", fail)
    assert (
        setup[0].client.post(setup[5], headers=headers(setup[1], "suite"), json=SPEC).status_code
        == 503
    )
    with Session(setup[0].app.state.engine) as session:
        assert session.scalar(select(SuiteRecord)) is None
        assert (
            session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.operation.startswith("create_test_suite:")
                )
            )
            is None
        )


def test_corruption_and_protected_downgrade(setup):
    first = create(setup)
    target = setup[0]
    config = migration_config(target.app.state.settings)
    with pytest.raises(RuntimeError, match="test suites"):
        command.downgrade(config, "0006_assessment")
    assert target.client.get("/health/ready").status_code == 200
    with Session(target.app.state.engine) as session, session.begin():
        row = session.get(SuiteRecord, first["suite_id"])
        body = copy.deepcopy(row.definition)
        body["cases"][0]["expected_stdout"] = "corrupted"
        row.definition = body
    assert (
        target.client.get(f"/v1/test-suites/{first['suite_id']}", headers=setup[1]).status_code
        == 409
    )


def test_empty_migration_roundtrip(service):
    target = service("assessment")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0006_assessment")
    assert target.client.get("/health/ready").status_code == 503
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200


@pytest.mark.parametrize("action", ["review", "retire"])
def test_empty_review_reason_is_rejected(setup, action):
    first = create(setup)
    assert (
        setup[0]
        .client.post(
            f"/v1/test-suites/{first['suite_id']}/{action}",
            headers=headers(setup[2], action, 1),
            json={"reason": "  "},
        )
        .status_code
        == 422
    )


def test_retired_content_keeps_old_suite_readable_but_closes_review(setup):
    first = create(setup)
    target, _, reviewer, _, revision, _ = setup
    assert (
        target.client.post(
            f"/v1/content-versions/{revision}/retire",
            headers=headers(reviewer, "withdraw", 2),
            json={"reason": "Withdraw content"},
        ).status_code
        == 200
    )
    path = f"/v1/test-suites/{first['suite_id']}"
    assert target.client.get(path, headers=reviewer).status_code == 200
    assert (
        target.client.post(
            path + "/review", headers=headers(reviewer, "review", 1), json={"reason": "Attempt"}
        ).status_code
        == 409
    )
    assert (
        target.client.post(
            path + "/retire",
            headers=headers(reviewer, "retire", 1),
            json={"reason": "Retire orphaned draft"},
        ).status_code
        == 200
    )


@pytest.mark.parametrize("action", ["review", "retire"])
def test_suite_reviewer_and_retirement_author_are_retained(setup, token, action):
    first = create(setup)
    subject = uuid4()
    auth = admin(token, subject)
    target = setup[0]
    assert (
        target.client.post(
            f"/v1/test-suites/{first['suite_id']}/{action}",
            headers=headers(auth, action, 1),
            json={"reason": "Synthetic independent decision"},
        ).status_code
        == 200
    )
    request_id = uuid4()
    event = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, event)
    with Session(target.app.state.engine) as session:
        assert session.get(AssessmentSubject, str(subject)).status == "restricted"
        row = session.get(SuiteRecord, first["suite_id"])
        assert (row.reviewed_by if action == "review" else row.retired_by) == str(subject)
    assert (
        target.client.get(f"/v1/test-suites/{first['suite_id']}", headers=auth).status_code == 409
    )


def test_sql_reference_is_bound_to_query_entrypoint(setup):
    target, author, reviewer, _, _, _ = setup
    package = copy.deepcopy(PACKAGE)
    package["tasks"][0].update(format="sql", reference_answer="SELECT 1;")
    revision = target.client.post(
        "/v1/content-families",
        headers=headers(author, "sql-family"),
        json={"name": "Synthetic SQL", "content": package},
    ).json()["revision_id"]
    assert (
        target.client.post(
            f"/v1/content-versions/{revision}/publish",
            headers=headers(reviewer, "sql-publish", 1),
            json={"reason": "Synthetic SQL review"},
        ).status_code
        == 200
    )
    body = copy.deepcopy(SPEC)
    body["format"] = "sql"
    body["reference"]["files"] = [{"path": "query.sql", "content": "SELECT 1;"}]
    for index, mutant in enumerate(body["mutants"]):
        mutant["source"]["files"] = [{"path": "query.sql", "content": f"SELECT {index + 2};"}]
    assert (
        target.client.post(
            f"/v1/content-versions/{revision}/tasks/sample/test-suites",
            headers=headers(author, "sql-suite"),
            json=body,
        ).status_code
        == 201
    )


def test_late_permission_failure_and_deletion_ack_rollback(setup, monkeypatch):
    target, author, _, subject, _, _ = setup
    calls = []

    def check(*_):
        calls.append(True)
        if len(calls) == 2:
            raise HTTPException(409)

    target.app.state.processing_access.check = check
    assert (
        target.client.post(setup[5], headers=headers(author, "suite"), json=SPEC).status_code == 409
    )
    with Session(target.app.state.engine) as session:
        assert session.scalar(select(SuiteRecord)) is None
    target.app.state.processing_access.check = lambda *_: None
    create(setup)
    import reverse_hr.domains.assessment_sessions as domain

    def fail(*_):
        raise HTTPException(503)

    monkeypatch.setattr(domain, "enqueue", fail)
    request_id = uuid4()
    event = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"candidate_id": subject, "request_id": request_id},
    )
    with pytest.raises(HTTPException), Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, event)
    with Session(target.app.state.engine) as session:
        assert not session.get(AssessmentSubject, str(subject)).blocked
        assert (
            session.scalar(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
            )
            is not None
        )
    assert (
        target.client.post(setup[5], headers=headers(author, "suite"), json=SPEC).status_code == 201
    )
