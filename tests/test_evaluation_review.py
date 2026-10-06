import copy
import hashlib
from unittest.mock import Mock
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_evaluation_artifacts import collect
from test_evaluation_artifacts import setup as artifact_setup
from test_evaluation_material import deletion
from test_event_transport import signatures as signatures_fixture

from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.evaluation import (
    EvaluationIntake,
    EvaluationSubject,
    process_deletion_request,
)
from reverse_hr.domains.evaluation_review import ReviewRecord
from reverse_hr.migrate import migration_config

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, monkeypatch, request):
    import test_assessment_sessions
    from test_assessment_content import PACKAGE

    package = copy.deepcopy(PACKAGE)
    rubric = package["tasks"][0]["rubric"]
    rubric[0]["points"], rubric[0]["evidence"] = 60, "artifact"
    rubric.append(
        rubric[0]
        | {"key": "clarity", "points": 40, "evidence": getattr(request, "param", "artifact")}
    )
    monkeypatch.setattr(test_assessment_sessions, "PACKAGE", package)
    source = artifact_setup.__wrapped__(service, token, signatures)
    assert collect(source)
    target, _, _, material_access, _ = source[0]
    target.app.state.material_access = material_access
    target.app.state.artifact_access = source[2]
    reviewer = uuid4()
    auth = token(reviewer, ("assessment_reviewer",), amr=["mfa"])
    return source, auth, reviewer


def path(setup):
    return f"/v1/evaluation-reviews/stages/{setup[0][0][2].aggregate_id}"


def body(setup, points=(50, 30)):
    file = setup[0][0][4][1]["files"][0]
    citation = {
        "path": file["path"],
        "file_digest": hashlib.sha256(file["content"].encode()).hexdigest(),
        "start_line": 1,
        "end_line": 1,
    }
    return {
        "reason": "Synthetic human review rationale",
        "decisions": [
            {
                "criterion_key": key,
                "points": value,
                "reason": "Synthetic criterion evidence explanation",
                "citations": [citation] if value is not None else [],
            }
            for key, value in zip(("shape", "clarity"), points, strict=True)
        ],
    }


def post(setup, payload=None, *, key="review-1", version=3, auth=None):
    return setup[0][0][0].client.post(
        path(setup) + "/reviews",
        json=payload or body(setup),
        headers=headers(auth or setup[1], key, version),
    )


def records(setup, model):
    with Session(setup[0][0][0].app.state.engine) as session:
        return session.scalars(select(model)).all()


def test_private_workspace_review_history_and_public_demo_score(setup):
    target = setup[0][0][0]
    workspace = target.client.get(path(setup), headers=setup[1])
    assert workspace.status_code == 200, workspace.text
    assert workspace.json()["material"]["task"]["reference_answer"]
    assert workspace.json()["source"]["files"]
    reply = post(setup)
    assert reply.status_code == 200, reply.text
    result = reply.json()
    assert result["score"] == 80 and result["confirmed_grade"] is None
    assert result["status"] == "reviewed" and result["version"] == 4
    assert result["latest"]["number"] == 1 and result["latest"]["reviewer_id"] == str(setup[2])
    assert post(setup).json() == result
    assert len(records(setup, ReviewRecord)) == 1
    event = setup[0][0][2]
    candidate = target.client.get(
        f"/v1/evaluations/stages/{event.aggregate_id}", headers=setup[0][0][4][0][2]
    )
    assert candidate.status_code == 200 and candidate.json()["score"] == 80
    assert candidate.json()["confirmed_grade"] is None and candidate.json()["demo"]
    assert (
        "reason" not in candidate.text
        and "citations" not in candidate.text
        and "reviewer_id" not in candidate.text
    )
    revised = post(setup, body(setup, (60, 40)), key="review-2", version=4)
    assert revised.status_code == 200 and revised.json()["score"] == 100
    assert post(setup).json() == revised.json()
    history = target.client.get(path(setup) + "/history", headers=setup[1])
    assert history.status_code == 200
    assert [r["score"] for r in history.json()] == [100, 80]
    assert [
        r["number"]
        for r in target.client.get(path(setup) + "/history?before=2", headers=setup[1]).json()
    ] == [1]
    events = records(setup, Outbox)
    assert sum(r.envelope["event_type"] == "evaluation.review_recorded.v1" for r in events) == 2
    for row in events:
        assert "Synthetic" not in str(row.envelope) and "citations" not in str(row.envelope)


@pytest.mark.parametrize(
    "roles,mfa",
    [
        (("candidate",), True),
        (("employer",), True),
        (("content_admin",), True),
        (("assessment_reviewer",), False),
    ],
)
def test_role_and_mfa_blocks_private_data(setup, token, roles, mfa):
    auth = token(roles=roles, amr=["mfa"] if mfa else [])
    target = setup[0][0][0]
    assert target.client.get(path(setup), headers=auth).status_code == 403
    assert target.client.get(path(setup) + "/history", headers=auth).status_code == 403
    assert post(setup, auth=auth).status_code == 403
    assert not records(setup, ReviewRecord)


def test_candidate_cannot_review_self_with_privileged_role(setup, token):
    candidate = setup[0][0][2].payload["candidate_id"]
    auth = token(candidate, ("assessment_reviewer",), amr=["mfa"])
    assert setup[0][0][0].client.get(path(setup), headers=auth).status_code == 403
    assert post(setup, auth=auth).status_code == 403


@pytest.mark.parametrize(
    "edit,code",
    [
        ("missing_citation", 422),
        ("wrong_path", 409),
        ("wrong_digest", 409),
        ("outside_lines", 409),
        ("reversed_lines", 422),
        ("path_traversal", 422),
        ("unknown_criterion", 409),
        ("duplicate_criterion", 422),
        ("too_many_points", 409),
        ("bool_points", 422),
        ("missing_reason", 422),
        ("whitespace_reason", 422),
    ],
)
def test_invalid_evidence_no_review_or_zero(setup, edit, code):
    payload = body(setup)
    first = payload["decisions"][0]
    citation = first["citations"][0]
    if edit == "missing_citation":
        first["citations"] = []
    elif edit == "wrong_path":
        citation["path"] = "absent.py"
    elif edit == "wrong_digest":
        citation["file_digest"] = "f" * 64
    elif edit == "outside_lines":
        citation["end_line"] = 2
    elif edit == "reversed_lines":
        citation["start_line"] = 2
    elif edit == "path_traversal":
        citation["path"] = "../main.py"
    elif edit == "unknown_criterion":
        first["criterion_key"] = "unknown"
    elif edit == "duplicate_criterion":
        payload["decisions"][1]["criterion_key"] = "shape"
    elif edit == "too_many_points":
        first["points"] = 61
    elif edit == "bool_points":
        first["points"] = True
    elif edit == "missing_reason":
        del first["reason"]
    else:
        payload["reason"] = "  "
    assert post(setup, payload).status_code == code
    assert not records(setup, ReviewRecord)
    assert records(setup, EvaluationIntake)[0].score is None


@pytest.mark.parametrize("setup", ["test_result"], indirect=True)
def test_source_citation_cannot_claim_hidden_tests_pass(setup):
    assert post(setup).status_code == 409
    reply = post(setup, body(setup, (50, None)))
    assert reply.status_code == 200 and reply.json()["score"] is None
    assert reply.json()["status"] == "needs_evidence"
    assert reply.json()["latest"]["decisions"][1]["points"] is None


def test_explicit_zero_with_evidence_is_manual_demo_decision(setup):
    reply = post(setup, body(setup, (0, 0)))
    assert reply.status_code == 200 and reply.json()["score"] == 0
    assert reply.json()["status"] == "reviewed"
    assert reply.json()["confirmed_grade"] is None


def test_stale_version_or_changed_idempotency_payload(setup):
    assert post(setup, version=2).status_code == 409
    assert post(setup).status_code == 200
    assert post(setup, key="stale").status_code == 409
    assert post(setup, body(setup, (60, 40))).status_code == 409
    assert len(records(setup, ReviewRecord)) == 1


def test_outbox_failure_rolls_back_review_score_cache(setup, monkeypatch):
    from reverse_hr.domains import evaluation_review

    original = evaluation_review.enqueue
    monkeypatch.setattr(evaluation_review, "enqueue", Mock(side_effect=RuntimeError()))
    assert post(setup).status_code == 500
    assert not records(setup, ReviewRecord)
    assert records(setup, EvaluationIntake)[0].score is None
    assert not records(setup, IdempotencyRecord)
    monkeypatch.setattr(evaluation_review, "enqueue", original)
    assert post(setup).status_code == 200


@pytest.mark.parametrize("code", [409, 503])
def test_live_permission_replay_and_workspace_fail_closed(setup, code):
    assert post(setup).status_code == 200
    setup[0][0][3].fetch = Mock(side_effect=HTTPException(code))
    target = setup[0][0][0]
    assert post(setup).status_code == code
    assert target.client.get(path(setup), headers=setup[1]).status_code == code
    assert target.client.get(path(setup) + "/history", headers=setup[1]).status_code == code
    assert len(records(setup, ReviewRecord)) == 1


def test_candidate_delete_scrubs_reviews_and_all_reviewer_command_caches(setup):
    assert post(setup).status_code == 200
    target, _, event, _, _ = setup[0][0]
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(event))
    assert not records(setup, ReviewRecord) and not records(setup, EvaluationIntake)
    assert not records(setup, IdempotencyRecord)
    assert post(setup).status_code == 404
    assert [r.envelope["event_type"] for r in records(setup, Outbox)] == [
        "evaluation.data_deleted.v1"
    ]


def test_reviewer_deletion_restricts_retained_authorship_and_blocks_access(setup):
    assert post(setup).status_code == 200
    target, _, event, _, _ = setup[0][0]
    request = deletion(event).model_copy(
        update={"payload": {"candidate_id": setup[2], "request_id": deletion(event).aggregate_id}}
    )
    request = request.model_copy(update={"aggregate_id": request.payload["request_id"]})
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, request)
    assert len(records(setup, ReviewRecord)) == 1
    assert not records(setup, IdempotencyRecord)
    assert any(
        r.envelope["event_type"] == "evaluation.data_restricted.v1" for r in records(setup, Outbox)
    )
    assert post(setup).status_code == 409
    # Erase the candidate's review, then replay the same deletion request with a new delivery ID.
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(event))
        process_deletion_request(session, request.model_copy(update={"event_id": uuid4()}))
    with Session(target.app.state.engine) as session:
        assert session.get(EvaluationSubject, str(setup[2])).deleted_at is not None
    assert (
        sum(
            r.envelope["event_type"] == "evaluation.data_deleted.v1" for r in records(setup, Outbox)
        )
        == 2
    )


def test_populated_review_downgrade_preserves_readiness(setup):
    assert post(setup).status_code == 200
    target = setup[0][0][0]
    with pytest.raises(RuntimeError, match="populated Evaluation"):
        command.downgrade(migration_config(target.app.state.settings), "0004_evaluation")
    assert target.client.get("/health/ready").status_code == 200


def test_missing_evidence_leaves_score_unset_then_revised(setup):
    pending = post(setup, body(setup, (None, None)))
    assert pending.status_code == 200 and pending.json()["score"] is None
    assert pending.json()["status"] == "needs_evidence"
    assert all(
        r["points"] is None and r["status"] == "pending"
        for r in records(setup, EvaluationIntake)[0].requirements
    )
    reviewed = post(setup, key="scored", version=4)
    assert reviewed.status_code == 200 and reviewed.json()["score"] == 80
    row = records(setup, EvaluationIntake)[0]
    assert [r["points"] for r in row.requirements] == [50, 30]
    assert all(
        r["status"] == "reviewed" and r["review_id"] == reviewed.json()["latest"]["review_id"]
        for r in row.requirements
    )


def test_candidate_delete_during_remote_admission_blocks_review(setup):
    target, _, event, access, _ = setup[0][0]
    original = access.fetch

    def fetch_then_delete(**refs):
        current = original(**refs)
        with Session(target.app.state.engine) as session, session.begin():
            process_deletion_request(session, deletion(event))
        return current

    access.fetch = fetch_then_delete
    assert post(setup).status_code == 409
    assert not records(setup, ReviewRecord)
    assert not records(setup, IdempotencyRecord)


def test_changed_version_during_admission_prevents_stale_review(setup):
    target, _, event, access, _ = setup[0][0]
    original = access.fetch

    def fetch_then_change(**refs):
        current = original(**refs)
        with Session(target.app.state.engine) as session, session.begin():
            session.get(EvaluationIntake, str(event.aggregate_id)).version += 1
        return current

    access.fetch = fetch_then_change
    assert post(setup).status_code == 409
    assert not records(setup, ReviewRecord)
    access.fetch = original
    assert post(setup, version=4).status_code == 200


def test_final_consent_guard_blocks_cached_replay_and_private_history(setup):
    assert post(setup).status_code == 200
    target = setup[0][0][0]
    target.app.state.processing_access.check_assessment = Mock(side_effect=HTTPException(409))
    assert post(setup).status_code == 409
    assert target.client.get(path(setup), headers=setup[1]).status_code == 409
    assert target.client.get(path(setup) + "/history", headers=setup[1]).status_code == 409
    assert len(records(setup, ReviewRecord)) == 1


def test_cached_source_corruption_blocks_review(setup):
    target, _, event, _, _ = setup[0][0]
    with Session(target.app.state.engine) as session, session.begin():
        row = session.get(EvaluationIntake, str(event.aggregate_id))
        row.source = {"files": [{"path": "main.py", "content": "changed source"}]}
    assert post(setup).status_code == 503
    assert not records(setup, ReviewRecord)


def test_missing_criterion_duplicate_citation_and_client_grade_rejected(setup):
    incomplete = body(setup)
    incomplete["decisions"] = incomplete["decisions"][:1]
    assert post(setup, incomplete).status_code == 409
    duplicated = body(setup)
    duplicated["decisions"][0]["citations"] *= 2
    assert post(setup, duplicated).status_code == 422
    assert post(setup, body(setup) | {"confirmed_grade": "senior"}).status_code == 422
    assert (
        setup[0][0][0].client.get(path(setup) + "/history?before=0", headers=setup[1]).status_code
        == 422
    )


def test_review_erase_ack_failure_preserves_history_score_cache(setup, monkeypatch):
    from reverse_hr.domains import evaluation

    assert post(setup).status_code == 200
    target, _, event, _, _ = setup[0][0]
    original = evaluation.enqueue
    monkeypatch.setattr(evaluation, "enqueue", Mock(side_effect=RuntimeError()))
    with pytest.raises(RuntimeError):
        with Session(target.app.state.engine) as session, session.begin():
            process_deletion_request(session, deletion(event))
    assert len(records(setup, ReviewRecord)) == 1
    assert records(setup, EvaluationIntake)[0].score == 80
    assert len(records(setup, IdempotencyRecord)) == 1
    monkeypatch.setattr(evaluation, "enqueue", original)
    assert post(setup).status_code == 200


def test_reviewer_restriction_after_initial_auth_blocks_commit(setup):
    target = setup[0][0][0]
    check = Mock(side_effect=[None, HTTPException(409)])
    target.app.state.processing_access.check = check
    assert post(setup).status_code == 409
    assert check.call_count == 2
    assert not records(setup, ReviewRecord)
    assert not records(setup, IdempotencyRecord)


def test_revised_missing_evidence_clears_previous_score_and_preserves_history(setup):
    assert post(setup).json()["score"] == 80
    changed = post(setup, body(setup, (50, None)), key="insufficient", version=4)
    assert changed.status_code == 200 and changed.json()["score"] is None
    assert changed.json()["status"] == "needs_evidence"
    assert records(setup, EvaluationIntake)[0].score is None
    history = setup[0][0][0].client.get(path(setup) + "/history", headers=setup[1]).json()
    assert [r["score"] for r in history] == [None, 80]
