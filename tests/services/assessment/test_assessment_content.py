import copy
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from types import SimpleNamespace
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.platform.app import create_app
from reverse_hr.platform.migrate import migration_config
from reverse_hr.platform.settings import Settings
from reverse_hr.services.assessment.domain.assessment import ContentFamily, ContentRevision
from reverse_hr.shared.db import IdempotencyRecord, Outbox
from tests.shared.test_access import headers

# Synthetic structure only: not a calibrated rubric or real benchmark.
PACKAGE = {
    "specialization": "synthetic-backend",
    "grade": "junior",
    "source_dataset": "synthetic-fixture",
    "source_version": "1",
    "demo": True,
    "competencies": [{"key": "structure", "description": "Synthetic competency"}],
    "tasks": [
        {
            "key": "sample",
            "format": "code",
            "instruction": "Synthetic prompt",
            "duration_seconds": 300,
            "reference_answer": "Synthetic reference",
            "rubric": [
                {
                    "key": "shape",
                    "competency": "structure",
                    "description": "Synthetic criterion",
                    "points": 100,
                    "evidence": "test_result",
                }
            ],
        }
    ],
}


@pytest.fixture(params=["sqlite", "postgres"])
def assessment(request, service, keys):
    if request.param == "sqlite":
        yield service("assessment")
        return
    url = os.getenv("HR_TEST_ASSESSMENT_DATABASE_URL")
    if not url:
        pytest.skip("Assessment PostgreSQL not configured")
    settings = Settings(service_name="assessment", database_url=url)
    command.upgrade(migration_config(settings), "head")
    app = create_app(settings)
    app.state.processing_access = SimpleNamespace(
        check=lambda *_: None, check_assessment=lambda *_: None
    )
    app.state.token_verifier.jwks.fetch_data = lambda: {"keys": [keys[1]]}
    with TestClient(app) as client:
        yield SimpleNamespace(app=app, client=client)


def create(assessment, auth):
    response = assessment.client.post(
        "/v1/content-families",
        headers=headers(auth, "family"),
        json={"name": "Synthetic family", "content": PACKAGE},
    )
    assert response.status_code == 201
    return response.json()


def admin(token, subject=None):
    return token(subject, ("content_admin",), amr=["mfa"])


def test_versions_remain_immutable_and_publication_requires_another_human(assessment, token):
    author = admin(token)
    reviewer = admin(token)
    first = create(assessment, author)
    path = f"/v1/content-versions/{first['revision_id']}"
    body = {"reason": "Synthetic human review"}
    assert (
        assessment.client.post(
            path + "/publish", headers=headers(author, "self", 1), json=body
        ).status_code
        == 403
    )
    published = assessment.client.post(
        path + "/publish", headers=headers(reviewer, "review", 1), json=body
    )
    assert published.status_code == 200
    assert published.json()["status"] == "published" and published.json()["version"] == 2
    assert (
        assessment.client.post(
            path + "/publish", headers=headers(reviewer, "review", 1), json=body
        ).json()
        == published.json()
    )
    assert (
        assessment.client.post(
            path + "/publish", headers=headers(reviewer, "other", 1), json=body
        ).status_code
        == 409
    )
    family_path = f"/v1/content-families/{first['family_id']}"
    changed = copy.deepcopy(PACKAGE)
    changed["source_version"] = "2"
    changed["tasks"][0]["instruction"] = "Different synthetic version"
    second = assessment.client.post(
        family_path + "/versions", headers=headers(author, "v2", 1), json=changed
    )
    assert second.status_code == 201
    assert second.json()["number"] == 2 and second.json()["status"] == "draft"
    assert assessment.client.get(family_path, headers=author).json()["version"] == 2
    assert assessment.client.get(path, headers=author).json()["content"] == PACKAGE
    assert assessment.client.put(path, headers=author, json=changed).status_code == 405
    assert (
        assessment.client.post(
            family_path + "/versions", headers=headers(author, "stale", 1), json=changed
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            family_path + "/versions",
            headers=headers(author, "changed-grade", 2),
            json=changed | {"grade": "lead"},
        ).status_code
        == 409
    )
    retired = assessment.client.post(
        path + "/retire", headers=headers(reviewer, "retire", 2), json=body
    )
    assert retired.status_code == 200 and retired.json()["status"] == "retired"
    assert retired.json()["content"] == PACKAGE and retired.json()["published_at"] is not None
    assert (
        assessment.client.post(
            path + "/publish", headers=headers(reviewer, "resurrect", 3), json=body
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            path + "/retire", headers=headers(reviewer, "retire", 2), json=body
        ).json()
        == retired.json()
    )
    with Session(assessment.app.state.engine) as session:
        row = session.get(ContentRevision, first["revision_id"])
        assert row.created_by != row.reviewed_by and row.review_reason == body["reason"]
        assert row.retirement_reason == body["reason"]
        envelopes = [
            row.envelope
            for row in session.scalars(select(Outbox))
            if row.envelope["aggregate_id"] == first["revision_id"]
        ]
        assert len(envelopes) == 3
        assert all(set(event["payload"]) == {"revision_id", "family_id"} for event in envelopes)


def test_catalog_is_admin_only_and_rechecks_privacy_on_replay(assessment, token):
    subject = uuid4()
    author = admin(token, subject)
    first = create(assessment, author)
    path = f"/v1/content-versions/{first['revision_id']}"
    for auth in (
        token(),
        token(roles=("employer",)),
        token(roles=("assessment_reviewer",), amr=["mfa"]),
        token(roles=("content_admin",)),
    ):
        assert assessment.client.get(path, headers=auth).status_code == 403
        assert (
            assessment.client.post(
                "/v1/content-families",
                headers=headers(auth),
                json={"name": "Synthetic", "content": PACKAGE},
            ).status_code
            == 403
        )
    assert assessment.client.get(path).status_code == 401

    def blocked(*_):
        raise HTTPException(409)

    assessment.app.state.processing_access.check = blocked
    assert assessment.client.get(path, headers=author).status_code == 409
    assert (
        assessment.client.post(
            "/v1/content-families",
            headers=headers(author, "family"),
            json={"name": "Synthetic family", "content": PACKAGE},
        ).status_code
        == 409
    )


def test_unavailable_privacy_leaves_no_catalog_effect(assessment, token):
    subject = uuid4()

    def unavailable(*_):
        raise HTTPException(503)

    assessment.app.state.processing_access.check = unavailable
    assert (
        assessment.client.post(
            "/v1/content-families",
            headers=headers(admin(token, subject)),
            json={"name": "Synthetic", "content": PACKAGE},
        ).status_code
        == 503
    )
    with Session(assessment.app.state.engine) as session:
        assert not list(
            session.scalars(
                select(ContentRevision).where(ContentRevision.created_by == str(subject))
            )
        )
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
            )
        )


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_reference",
        "duplicate_competency",
        "duplicate_task",
        "duplicate_criterion",
        "bad_points",
        "boolean_points",
        "long_duration",
        "non_demo",
        "unknown_field",
        "unsupported_format",
        "mismatched_evidence",
        "oversized",
        "non_boolean_demo",
    ],
)
def test_invalid_manifest_has_no_effect(service, token, invalid):
    assessment = service("assessment")
    body = copy.deepcopy(PACKAGE)
    task = body["tasks"][0]
    if invalid == "missing_reference":
        task["rubric"][0]["competency"] = "unknown"
    elif invalid == "duplicate_competency":
        body["competencies"] *= 2
    elif invalid == "duplicate_task":
        body["tasks"] *= 2
    elif invalid == "duplicate_criterion":
        task["rubric"] *= 2
    elif invalid == "bad_points":
        task["rubric"][0]["points"] = 99
    elif invalid == "boolean_points":
        task["rubric"][0]["points"] = True
    elif invalid == "long_duration":
        body["tasks"] = [dict(task, key=f"task_{i}", duration_seconds=3600) for i in range(3)]
    elif invalid == "non_demo":
        body["demo"] = False
    elif invalid == "unknown_field":
        body["confirmed_grade"] = "lead"
    elif invalid == "mismatched_evidence":
        task["format"] = "voice"
    elif invalid == "oversized":
        body["tasks"] = [dict(task, key=f"task_{i}", instruction="x" * 19000) for i in range(14)]
    elif invalid == "non_boolean_demo":
        body["demo"] = 1
    else:
        task["format"] = "text_quiz"
    assert (
        assessment.client.post(
            "/v1/content-families",
            headers=headers(admin(token)),
            json={"name": "Synthetic", "content": body},
        ).status_code
        == 422
    )
    with Session(assessment.app.state.engine) as session:
        assert session.scalar(select(ContentFamily)) is None
        assert session.scalar(select(Outbox)) is None
        assert session.scalar(select(IdempotencyRecord)) is None


def test_content_history_downgrade_is_protected(service, token):
    assessment = service("assessment")
    config = migration_config(assessment.app.state.settings)
    command.downgrade(config, "0001_transport")
    command.upgrade(config, "head")
    first = create(assessment, admin(token))
    with pytest.raises(RuntimeError, match="populated assessment content"):
        command.downgrade(config, "0001_transport")
    with Session(assessment.app.state.engine) as session:
        assert session.get(ContentRevision, first["revision_id"]).content == PACKAGE


def test_postgres_concurrent_content_versions_have_one_winner(assessment, token):
    if assessment.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency")
    author = admin(token)
    first = create(assessment, author)
    barrier = Barrier(2)

    def run(key):
        barrier.wait(timeout=5)
        return assessment.client.post(
            f"/v1/content-families/{first['family_id']}/versions",
            headers=headers(author, key, 1),
            json=PACKAGE,
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(run, ["first", "second"])) == [201, 409]
    with Session(assessment.app.state.engine) as session:
        assert (
            len(
                list(
                    session.scalars(
                        select(ContentRevision).where(
                            ContentRevision.family_id == first["family_id"]
                        )
                    )
                )
            )
            == 2
        )


def test_catalog_transaction_rolls_back_and_key_can_retry(service, token, monkeypatch):
    import reverse_hr.services.assessment.domain.assessment as domain

    assessment = service("assessment")
    author = admin(token)
    original = domain.enqueue

    def fail(*_):
        raise RuntimeError("synthetic transaction failure")

    monkeypatch.setattr(domain, "enqueue", fail)
    body = {"name": "Synthetic family", "content": PACKAGE}
    assert (
        assessment.client.post(
            "/v1/content-families", headers=headers(author, "family"), json=body
        ).status_code
        == 500
    )
    with Session(assessment.app.state.engine) as session:
        assert session.scalar(select(ContentFamily)) is None
        assert session.scalar(select(ContentRevision)) is None
        assert session.scalar(select(IdempotencyRecord)) is None
    monkeypatch.setattr(domain, "enqueue", original)
    assert (
        assessment.client.post(
            "/v1/content-families", headers=headers(author, "family"), json=body
        ).status_code
        == 201
    )


@pytest.mark.parametrize("race", ["duplicate", "deletion"])
def test_postgres_session_commands_serialize_with_deletion(assessment, token, race):
    if assessment.app.state.engine.dialect.name != "postgresql":
        pytest.skip("PostgreSQL concurrency")
    from reverse_hr.services.assessment.domain.assessment_sessions import (
        AssessmentSubject,
        PracticalSession,
        process_deletion_request,
    )
    from tests.services.assessment.test_assessment_sessions import deletion, plan

    version, _, _ = plan(assessment, token)
    subject = uuid4()
    auth = token(subject)
    body = {"plan_version_id": version["plan_version_id"], "assessment_consent_id": str(uuid4())}
    barrier = Barrier(2)

    def create():
        barrier.wait(timeout=5)
        return assessment.client.post(
            "/v1/assessment-sessions", headers=headers(auth, "first"), json=body
        ).status_code

    def other():
        barrier.wait(timeout=5)
        if race == "duplicate":
            return assessment.client.post(
                "/v1/assessment-sessions", headers=headers(auth, "second"), json=body
            ).status_code
        with Session(assessment.app.state.engine) as session, session.begin():
            process_deletion_request(session, deletion(subject))
        return "deleted"

    with ThreadPoolExecutor(max_workers=2) as pool:
        first, second = pool.submit(create), pool.submit(other)
        result1, result2 = first.result(timeout=10), second.result(timeout=10)
    with Session(assessment.app.state.engine) as session:
        records = list(
            session.scalars(
                select(PracticalSession).where(PracticalSession.candidate_id == str(subject))
            )
        )
        if race == "duplicate":
            assert sorted([result1, result2]) == [201, 409]
            assert len(records) == 1
        else:
            assert result1 in (201, 409) and result2 == "deleted"
            assert records == []
            assert session.get(AssessmentSubject, str(subject)).blocked
            assert not list(
                session.scalars(
                    select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject))
                )
            )
