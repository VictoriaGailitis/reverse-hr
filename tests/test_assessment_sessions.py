import copy
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_assessment_content import PACKAGE, admin
from test_processing_access import connect_access
from test_processing_access import signing as signing_fixture

from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.assessment import ContentRevision
from reverse_hr.domains.assessment_sessions import (
    AssessmentSubject,
    PracticalSession,
    process_deletion_request,
)
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import (
    ASSESSMENT_REQUEST_CONTEXT,
    ASSESSMENT_RESPONSE_CONTEXT,
    REQUEST_CONTEXT,
    AssessmentPermissionRequest,
    AssessmentPermissionStatus,
    canonical,
    sign,
)
from reverse_hr.settings import Settings


def plan(assessment, token, package=None):
    author, reviewer = admin(token), admin(token)
    response = assessment.client.post(
        "/v1/content-families",
        headers=headers(author),
        json={"name": "Synthetic", "content": package or PACKAGE},
    )
    assert response.status_code == 201
    content = response.json()
    path = f"/v1/content-versions/{content['revision_id']}"
    assert (
        assessment.client.post(
            path + "/publish",
            headers=headers(reviewer, "review", 1),
            json={"reason": "Synthetic human review"},
        ).status_code
        == 200
    )
    reply = assessment.client.post(
        "/v1/assessment-plans",
        headers=headers(author, "plan"),
        json={
            "name": "Synthetic plan",
            "revision_ids": [content["revision_id"]],
            "reason": "Synthetic plan review",
        },
    )
    assert reply.status_code == 201
    return reply.json(), content, author


def make_session(assessment, token, version, subject=None, key="session", consent=None):
    auth = token(subject)
    body = {
        "plan_version_id": version["plan_version_id"],
        "assessment_consent_id": str(consent or uuid4()),
    }
    reply = assessment.client.post("/v1/assessment-sessions", headers=headers(auth, key), json=body)
    return reply, auth, body


def test_pinned_session_ownership_no_answers_and_cancel_replay(service, token):
    assessment = service("assessment")
    version, content, author = plan(assessment, token)
    candidate = uuid4()
    reply, auth, body = make_session(assessment, token, version, candidate)
    assert reply.status_code == 201
    session_id = reply.json()["session_id"]
    path = f"/v1/assessment-sessions/{session_id}"
    assert reply.json()["status"] == "preflight"
    stage = reply.json()["stages"][0]
    assert set(stage) == {
        "stage_id",
        "revision_id",
        "task_key",
        "format",
        "instruction",
        "duration_seconds",
    }
    assert "Synthetic reference" not in reply.text and "rubric" not in reply.text
    assert assessment.client.get(path, headers=token()).status_code == 404
    assert (
        assessment.client.post(path + "/cancel", headers=headers(token(), "foreign", 1)).status_code
        == 404
    )
    assert (
        assessment.client.post(
            "/v1/assessment-sessions", headers=headers(token(candidate), "duplicate"), json=body
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            "/v1/assessment-sessions", headers=headers(auth, "session"), json=body
        ).json()
        == reply.json()
    )
    # New content version and retirement cannot rewrite an existing pinned session.
    changed = copy.deepcopy(PACKAGE)
    changed["tasks"][0]["instruction"] = "New instruction"
    assert (
        assessment.client.post(
            f"/v1/content-families/{content['family_id']}/versions",
            headers=headers(author, "v2", 1),
            json=changed,
        ).status_code
        == 201
    )
    assert (
        assessment.client.post(
            f"/v1/assessment-plans/{version['plan_version_id']}/retire",
            headers=headers(author, "retire", 1),
            json={"reason": "Synthetic retirement"},
        ).status_code
        == 200
    )
    assert assessment.client.get(path, headers=auth).json()["stages"] == reply.json()["stages"]
    assert assessment.client.get("/v1/assessment-plans", headers=auth).json() == []
    cancelled = assessment.client.post(path + "/cancel", headers=headers(auth, "cancel", 1))
    assert cancelled.status_code == 200 and cancelled.json()["status"] == "cancelled"
    assert "stages" not in cancelled.json()
    assert (
        assessment.client.post(path + "/cancel", headers=headers(auth, "cancel", 1)).json()
        == cancelled.json()
    )
    assert (
        assessment.client.post(
            "/v1/assessment-sessions", headers=headers(auth, "session"), json=body
        ).json()["status"]
        == "cancelled"
    )
    assert (
        assessment.client.post(
            "/v1/assessment-sessions", headers=headers(token(), "retired"), json=body
        ).status_code
        == 409
    )


def test_plan_rejects_draft_duplicates_and_mixed_grade(service, token):
    assessment = service("assessment")
    author = admin(token)
    draft = assessment.client.post(
        "/v1/content-families",
        headers=headers(author),
        json={"name": "Synthetic", "content": PACKAGE},
    ).json()
    body = {"name": "Synthetic", "revision_ids": [draft["revision_id"]], "reason": "Synthetic"}
    assert (
        assessment.client.post(
            "/v1/assessment-plans", headers=headers(author, "draft"), json=body
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            "/v1/assessment-plans",
            headers=headers(author, "duplicate"),
            json=body | {"revision_ids": [draft["revision_id"]] * 2},
        ).status_code
        == 422
    )
    assert (
        assessment.client.post(
            "/v1/assessment-plans", headers=headers(token(), "candidate"), json=body
        ).status_code
        == 403
    )
    assert (
        assessment.client.post(
            "/v1/assessment-sessions",
            headers=headers(token()),
            json={
                "plan_version_id": str(uuid4()),
                "assessment_consent_id": str(uuid4()),
                "candidate_id": str(uuid4()),
            },
        ).status_code
        == 422
    )
    v1, c1, _ = plan(assessment, token)
    _, c2, _ = plan(assessment, token, PACKAGE | {"grade": "middle"})
    mixed = body | {"revision_ids": [c1["revision_id"], c2["revision_id"]]}
    assert (
        assessment.client.post(
            "/v1/assessment-plans", headers=headers(author, "mixed"), json=mixed
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            f"/v1/content-versions/{c1['revision_id']}/retire",
            headers=headers(author, "content-retire", 2),
            json={"reason": "Synthetic"},
        ).status_code
        == 200
    )
    assert make_session(assessment, token, v1)[0].status_code == 409
    assert (
        assessment.client.get("/v1/assessment-plans", headers=token()).json()[0]["grade"]
        == "middle"
    )


def test_permission_refusal_rolls_back_and_cancel_works_without_materials(service, token):
    assessment = service("assessment")
    version, _, _ = plan(assessment, token)
    candidate = uuid4()

    def denied(*_):
        raise HTTPException(409)

    assessment.app.state.processing_access.check_assessment = denied
    reply, auth, body = make_session(assessment, token, version, candidate)
    assert reply.status_code == 409
    with Session(assessment.app.state.engine) as session:
        assert session.scalar(select(PracticalSession)) is None
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(candidate))
            )
        )
    assessment.app.state.processing_access.check_assessment = lambda *_: None
    created = assessment.client.post(
        "/v1/assessment-sessions", headers=headers(auth, "session"), json=body
    )
    assert created.status_code == 201
    path = f"/v1/assessment-sessions/{created.json()['session_id']}"
    assessment.app.state.processing_access.check_assessment = denied
    assert assessment.client.get(path, headers=auth).status_code == 409
    assert (
        assessment.client.post(
            "/v1/assessment-sessions", headers=headers(auth, "session"), json=body
        ).status_code
        == 409
    )
    cancelled = assessment.client.post(path + "/cancel", headers=headers(auth, "cancel", 1))
    assert cancelled.status_code == 200 and "stages" not in cancelled.json()


def deletion(subject):
    request_id = uuid4()
    return EventEnvelope(
        event_type="privacy.deletion_requested.v1",
        producer="privacy",
        correlation_id=uuid4(),
        aggregate_id=request_id,
        aggregate_version=1,
        payload={"request_id": request_id, "candidate_id": subject},
    )


def test_deletion_scrubs_sessions_keeps_other_candidate_and_blocks_recreation(service, token):
    assessment = service("assessment")
    version, _, author = plan(assessment, token)
    candidate, other = uuid4(), uuid4()
    own, auth, body = make_session(assessment, token, version, candidate)
    foreign, _, _ = make_session(assessment, token, version, other)
    event = deletion(candidate)
    with Session(assessment.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, event)
        assert not process_deletion_request(session, event)
    assert (
        assessment.client.get(
            f"/v1/assessment-sessions/{own.json()['session_id']}", headers=auth
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            "/v1/assessment-sessions", headers=headers(auth, "session"), json=body
        ).status_code
        == 409
    )
    with Session(assessment.app.state.engine) as session:
        assert session.get(PracticalSession, own.json()["session_id"]) is None
        assert session.get(PracticalSession, foreign.json()["session_id"]) is not None
        assert session.get(AssessmentSubject, str(candidate)).status == "deleted"
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(candidate))
            )
        )
        acks = [
            row
            for row in session.scalars(select(Outbox))
            if row.envelope["aggregate_id"] == str(event.aggregate_id)
        ]
        assert len(acks) == 1 and acks[0].envelope["event_type"] == "assessment.data_deleted.v1"
    # Content-author refs are retained, and must not be falsely reported as deleted.
    with Session(assessment.app.state.engine) as session, session.begin():
        author_id = session.scalar(select(ContentRevision)).created_by
        process_deletion_request(session, deletion(UUID(author_id)))
        assert session.get(AssessmentSubject, author_id).status == "restricted"
    assert (
        assessment.client.get(
            f"/v1/content-versions/{version['plan_version_id']}", headers=author
        ).status_code
        == 409
    )


def test_deletion_rollback_and_conflicting_ticket(service, token):
    assessment = service("assessment")
    version, _, _ = plan(assessment, token)
    candidate = uuid4()
    created, _, _ = make_session(assessment, token, version, candidate)
    event = deletion(candidate)
    with (
        pytest.raises(RuntimeError),
        Session(assessment.app.state.engine) as session,
        session.begin(),
    ):
        process_deletion_request(session, event)
        session.flush()
        raise RuntimeError("Synthetic rollback")
    with Session(assessment.app.state.engine) as session:
        assert session.get(PracticalSession, created.json()["session_id"]) is not None
        assert not session.get(AssessmentSubject, str(candidate)).blocked
    with Session(assessment.app.state.engine) as session, session.begin():
        process_deletion_request(session, event)
    with (
        pytest.raises(HTTPException),
        Session(assessment.app.state.engine) as session,
        session.begin(),
    ):
        process_deletion_request(session, deletion(candidate))


def test_signed_assessment_permission_and_revocation(service, token, permission_signatures):
    signing = permission_signatures
    assessment, privacy = service("assessment"), service("privacy")
    privacy.app.state.privacy_signatures = signing["privacy"]
    access = connect_access("assessment", privacy, signing)

    def send(body, signature):
        response = privacy.client.post(
            "/internal/v1/assessment-permission",
            content=body,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise HTTPException(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    access.send_assessment = send
    assessment.app.state.processing_access = access
    version, _, _ = plan(assessment, token)
    candidate = uuid4()
    candidate_auth = token(candidate)
    consent = privacy.client.post(
        "/v1/consents",
        headers=headers(candidate_auth),
        json={"purpose": "assessment", "document_version": "demo-v1"},
    ).json()
    wrong = privacy.client.post(
        "/v1/consents",
        headers=headers(candidate_auth, "recording"),
        json={"purpose": "recording", "document_version": "demo-v1"},
    ).json()
    assert (
        make_session(assessment, token, version, candidate, consent=UUID(wrong["consent_id"]))[
            0
        ].status_code
        == 409
    )
    created, _, body = make_session(
        assessment, token, version, candidate, consent=UUID(consent["consent_id"])
    )
    assert created.status_code == 201
    assert (
        make_session(assessment, token, version, consent=UUID(consent["consent_id"]))[0].status_code
        == 409
    )
    assert (
        privacy.client.post(
            f"/v1/consents/{consent['consent_id']}/revoke",
            headers=headers(candidate_auth, "revoke", 1),
        ).status_code
        == 200
    )
    assert (
        assessment.client.get(
            f"/v1/assessment-sessions/{created.json()['session_id']}", headers=candidate_auth
        ).status_code
        == 409
    )
    assert (
        assessment.client.post(
            "/v1/assessment-sessions", headers=headers(candidate_auth, "session"), json=body
        ).status_code
        == 409
    )


def test_signed_permission_replay_wrong_context_staleness_and_binding(
    service, permission_signatures
):
    signing = permission_signatures
    privacy = service("privacy")
    privacy.app.state.privacy_signatures = signing["privacy"]
    request = AssessmentPermissionRequest(
        candidate_id=uuid4(),
        consent_id=uuid4(),
        requester="assessment",
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )
    path = "/internal/v1/assessment-permission"

    def send(model, context=ASSESSMENT_REQUEST_CONTEXT):
        return privacy.client.post(
            path,
            content=canonical(model),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": sign(signing["assessment"], context, model),
            },
        )

    assert send(request, REQUEST_CONTEXT).status_code == 401
    assert (
        send(
            request.model_copy(update={"issued_at": datetime.now(UTC) - timedelta(minutes=1)})
        ).status_code
        == 401
    )
    response = send(request)
    assert response.status_code == 200 and not response.json()["allowed"]
    assert send(request).status_code == 401
    from reverse_hr.processing_access import ProcessingAccess

    access = ProcessingAccess(Settings(service_name="assessment"))
    access._signatures = signing["assessment"]

    def tampered(raw, signature):
        incoming = AssessmentPermissionRequest.model_validate_json(raw)
        status = AssessmentPermissionStatus(**incoming.model_dump(), allowed=True)
        status = status.model_copy(update={"consent_id": uuid4()})
        return canonical(status), sign(signing["privacy"], ASSESSMENT_RESPONSE_CONTEXT, status)

    access.send_assessment = tampered
    with pytest.raises(HTTPException) as error:
        access.check_assessment(uuid4(), uuid4())
    assert error.value.status_code == 503


@pytest.fixture
def permission_signatures():
    return signing_fixture.__wrapped__()
