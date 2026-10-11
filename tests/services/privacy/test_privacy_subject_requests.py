"""Migrated owners and actual signed, consent-independent rights delivery."""

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.coordination.privacy_request_exchange import RightsAccess, RightsExchange, context
from reverse_hr.services.candidate.domain.candidate_grades import CandidateDecision
from reverse_hr.services.privacy.domain.privacy import DeletionTarget, finalize_deletion
from reverse_hr.services.privacy.domain.privacy_requests import RequestHistory, SubjectRequest
from reverse_hr.shared.signing import canonical, sign
from tests.integration.test_achievements_integration import connect, synchronize
from tests.integration.test_achievements_integration import setup as market_setup
from tests.integration.test_achievements_integration import signatures as signatures
from tests.integration.test_matching_hiring import invite
from tests.shared.test_access import headers


@pytest.fixture
def setup(service, token, signatures):
    s = market_setup.__wrapped__(service, token, signatures)
    for name in ("privacy", "candidate", "achievements", "hiring"):
        target = s.targets[name]
        access = RightsAccess(target.app.state.settings)
        access._signatures, access._send = signatures[name], s.sender
        target.app.state.rights_access = access
    s.officer = token(uuid4(), ("privacy_officer",), amr=["mfa"])
    s.other = token(uuid4())
    return s


def submit(s, kind="access", **kwargs):
    response = s.privacy.client.post(
        "/v1/data-subject-requests",
        json=dict(kind=kind, reason="Please process my own data", **kwargs),
        headers=headers(s.auth, str(uuid4())),
    )
    assert response.status_code == 201, response.text
    return response.json()


def approve(s, row):
    path = "/v1/data-subject-requests/" + row["request_id"]
    claimed = s.privacy.client.post(
        path + "/claim", headers=headers(s.officer, str(uuid4()), row["version"])
    )
    assert claimed.status_code == 200, claimed.text
    decided = s.privacy.client.post(
        path + "/decision",
        json=dict(outcome="approved", reason="Reviewed verified ownership"),
        headers=headers(s.officer, str(uuid4()), claimed.json()["version"]),
    )
    assert decided.status_code == 200, decided.text
    return decided.json()


@pytest.mark.parametrize("domain", ["privacy", "candidate", "achievements", "hiring"])
def test_actual_access_exports_private_owned_data_with_auth(setup, domain):
    s = setup
    invitation = invite(s).json()
    synchronize(s, connect(s))
    row = submit(s, domain=domain)
    path = "/v1/data-subject-requests/" + row["request_id"]
    assert s.privacy.client.get(path + "/export", headers=s.auth).status_code == 409
    assert s.privacy.client.get(path, headers=s.other).status_code == 404
    row = approve(s, row)
    result = s.privacy.client.get(path + "/export", headers=s.auth)
    assert result.status_code == 200, result.text
    assert result.headers["cache-control"] == "no-store"
    payload = result.json()
    assert payload["complete"] is False and payload["scope"] == domain
    assert payload["coverage"] == "legacy_projection"
    data = payload["data"]
    if domain == "candidate":
        assert data["profile"]["specialization"] == "backend"
        assert data["qualifications"][0]["target_grade"] == "middle"
        assert "reviewer_id" not in data["qualifications"][0]
    elif domain == "achievements":
        assert len(data["achievements"]) == 1 and data["connections"][0]["status"] == "active"
    elif domain == "hiring":
        assert data["invitations"][0]["invitation_id"] == invitation["invitation_id"]
        assert "employer_contact" not in data["invitations"][0]
    else:
        assert data["consents"] and data["requests"]
    assert s.privacy.client.get(path, headers=s.auth).json()["status"] == "approved"
    assert s.privacy.client.get(path + "/export", headers=s.auth).status_code == 200


def test_global_restriction_immediate_reversible_and_scope_isolation(setup):
    s = setup
    before = s.candidate.client.get("/v1/candidates/me", headers=s.auth)
    assert before.status_code == 200
    restriction = submit(s, "restriction")
    assert s.candidate.client.get("/v1/candidates/me", headers=s.auth).status_code == 409
    assert s.hiring.client.get("/v1/invitations", headers=s.auth).status_code == 409
    path = "/v1/data-subject-requests/" + restriction["request_id"]
    withdrawn = s.privacy.client.post(path + "/withdraw", headers=headers(s.auth, "withdraw", 1))
    assert withdrawn.status_code == 200
    assert s.candidate.client.get("/v1/candidates/me", headers=s.auth).status_code == 200
    assert len(s.privacy.client.get(path + "/history", headers=s.auth).json()) == 2
    scoped = submit(s, "restriction", domain="hiring")
    assert s.hiring.client.get("/v1/invitations", headers=s.auth).status_code == 409
    assert s.candidate.client.get("/v1/candidates/me", headers=s.auth).status_code == 200
    assert scoped["restriction_active"]


def test_purpose_restriction_blocks_published_profile_not_self_rights(setup):
    s = setup
    restriction = submit(s, "restriction", purpose="profile_publication")
    with pytest.raises(HTTPException) as error:
        s.hiring.app.state.market_access.require(
            "candidate", "profile", candidate_id=s.candidate_id
        )
    assert error.value.status_code == 409
    assert s.candidate.client.get("/v1/candidates/me", headers=s.auth).status_code == 200
    own = approve(s, submit(s, domain="candidate"))
    assert (
        s.privacy.client.get(
            "/v1/data-subject-requests/" + own["request_id"] + "/export", headers=s.auth
        ).status_code
        == 200
    )
    approve(s, restriction)
    assert s.privacy.client.get(
        "/v1/data-subject-requests/" + restriction["request_id"], headers=s.auth
    ).json()["restriction_active"]


def test_signed_correction_executes_only_declaration_and_retries_once(setup):
    s = setup
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    with Session(s.candidate.app.state.engine) as session:
        original = [row.summary for row in session.scalars(select(CandidateDecision))]
    row = approve(
        s,
        submit(
            s,
            "correction",
            domain="candidate",
            source_version=profile["version"],
            proposed_changes=dict(
                display_name="Corrected own name", specialization="backend", declared_grade="junior"
            ),
        ),
    )
    path = "/v1/data-subject-requests/" + row["request_id"]
    result = s.privacy.client.post(
        path + "/execute", headers=headers(s.officer, "correction", row["version"])
    )
    assert result.status_code == 200, result.text
    assert result.json()["status"] == "completed"
    replay = s.privacy.client.post(
        path + "/execute", headers=headers(s.officer, "correction", row["version"])
    )
    assert replay.status_code == 200, replay.text
    current = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    assert (
        current["display_name"] == "Corrected own name"
        and current["version"] == profile["version"] + 1
    )
    assert current["confirmed_grade"] == "middle"
    with Session(s.candidate.app.state.engine) as session:
        assert original == [row.summary for row in session.scalars(select(CandidateDecision))]


def test_officer_mfa_independence_and_competing_claims(setup, token):
    s = setup
    row = submit(s, domain="privacy")
    path = "/v1/data-subject-requests/" + row["request_id"]
    assert (
        s.privacy.client.post(
            path + "/claim", headers=headers(token(uuid4(), ("privacy_officer",)), "no-mfa", 1)
        ).status_code
        == 403
    )
    assert (
        s.privacy.client.post(
            path + "/claim",
            headers=headers(
                token(s.candidate_id, ("candidate", "privacy_officer"), amr=["mfa"]), "self", 1
            ),
        ).status_code
        == 403
    )

    dual = token(s.candidate_id, ("candidate", "privacy_officer"), amr=["mfa"])
    assert s.privacy.client.get(path, headers=dual).status_code == 200
    assert s.privacy.client.get(path + "/history", headers=dual).status_code == 200

    def run(_):
        return s.privacy.client.post(
            path + "/claim", headers=headers(s.officer, str(uuid4()), 1)
        ).status_code

    with ThreadPoolExecutor(2) as pool:
        assert sorted(pool.map(run, range(2))) == [200, 409]


def test_signed_export_replay_cross_scope_and_deletion(setup, signatures):
    s = setup
    row = approve(s, submit(s, domain="candidate"))
    body = RightsExchange(
        requester="privacy",
        operation="export",
        candidate_id=s.candidate_id,
        request_id=row["request_id"],
        revision=row["version"],
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
    )
    signed = sign(signatures["privacy"], context("candidate", "export", "request"), body)

    def send(value=body, signature=signed):
        return s.candidate.client.post(
            "/internal/v1/subject-rights/export",
            content=canonical(value),
            headers={"X-HR-Signature": signature, "Content-Type": "application/json"},
        )

    assert send().status_code == 200
    assert send().status_code == 401
    foreign = body.model_copy(update={"candidate_id": uuid4(), "nonce": uuid4()})
    assert (
        send(
            foreign, sign(signatures["privacy"], context("candidate", "export", "request"), foreign)
        ).status_code
        == 409
    )
    from reverse_hr.shared.db import IdempotencyRecord

    with Session(s.privacy.app.state.engine) as session:
        assert (
            session.scalar(
                select(IdempotencyRecord).where(
                    IdempotencyRecord.operation.like("subject_claim:%"),
                    IdempotencyRecord.response.contains(str(s.candidate_id)),
                )
            )
            is not None
        )
    deleted = s.privacy.client.post("/v1/deletion-requests", headers=headers(s.auth, "delete"))
    assert deleted.status_code == 202, deleted.text
    assert (
        s.privacy.client.get(
            "/v1/data-subject-requests/" + row["request_id"] + "/export", headers=s.auth
        ).status_code
        == 409
    )
    with Session(s.privacy.app.state.engine) as session, session.begin():
        from reverse_hr.services.privacy.domain.privacy import DeletionRequest

        job = session.get(DeletionRequest, deleted.json()["request_id"])
        for target in session.scalars(
            select(DeletionTarget).where(DeletionTarget.request_id == job.request_id)
        ):
            if target.service != "privacy":
                target.status = "deleted"
        session.flush()
        assert finalize_deletion(session, job, uuid4())
    with Session(s.privacy.app.state.engine) as session:
        assert list(session.scalars(select(SubjectRequest))) == []
        assert list(session.scalars(select(RequestHistory))) == []
        assert (
            list(
                session.scalars(
                    select(IdempotencyRecord).where(
                        IdempotencyRecord.operation != "request_deletion",
                        IdempotencyRecord.response.contains(str(s.candidate_id)),
                    )
                )
            )
            == []
        )


def test_all_access_supported_and_verified_evidence_correction_rejected(setup):
    s = setup
    assert (
        s.privacy.client.post(
            "/v1/data-subject-requests",
            json=dict(kind="access", reason="all data"),
            headers=headers(s.auth, "all"),
        ).status_code
        == 201
    )
    assert (
        s.privacy.client.post(
            "/v1/data-subject-requests",
            json=dict(
                kind="correction",
                domain="candidate",
                reason="change grade",
                source_version=1,
                proposed_changes=dict(confirmed_grade="lead"),
            ),
            headers=headers(s.auth, "grade"),
        ).status_code
        == 422
    )


def test_export_withdrawal_race_never_delivers_stale_authorization(setup):
    s = setup
    row = approve(s, submit(s, domain="candidate"))
    path = "/v1/data-subject-requests/" + row["request_id"]
    access = s.privacy.app.state.rights_access
    original = access.call

    def racing(*args, **kwargs):
        result = original(*args, **kwargs)
        response = s.privacy.client.post(
            path + "/withdraw", headers=headers(s.auth, "withdraw-race", row["version"])
        )
        assert response.status_code == 200
        return result

    access.call = racing
    assert s.privacy.client.get(path + "/export", headers=s.auth).status_code == 409


def correction_request(s):
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    return approve(
        s,
        submit(
            s,
            "correction",
            domain="candidate",
            source_version=profile["version"],
            proposed_changes=dict(
                display_name="Requested corrected name",
                specialization="backend",
                declared_grade="junior",
            ),
        ),
    ), profile


def test_lost_correction_receipt_retry_no_duplicate_and_withdraw_locked(setup):
    s = setup
    row, profile = correction_request(s)
    path = "/v1/data-subject-requests/" + row["request_id"]
    access = s.privacy.app.state.rights_access
    original = access.call

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        pending = s.privacy.client.get(path, headers=s.auth).json()
        assert pending["status"] == "applying"
        assert (
            s.privacy.client.post(
                path + "/withdraw", headers=headers(s.auth, "withdraw-too-late", pending["version"])
            ).status_code
            == 409
        )
        raise HTTPException(503)

    access.call = lost
    assert (
        s.privacy.client.post(
            path + "/execute", headers=headers(s.officer, "same-command", row["version"])
        ).status_code
        == 503
    )
    access.call = original
    result = s.privacy.client.post(
        path + "/execute", headers=headers(s.officer, "same-command", row["version"])
    )
    assert result.status_code == 200, result.text
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["version"]
        == profile["version"] + 1
    )


def test_deleted_officer_applying_job_can_reassign_without_reapplying(setup, token):
    from reverse_hr.services.privacy.domain.privacy_requests import scrub

    s = setup
    row, profile = correction_request(s)
    path = "/v1/data-subject-requests/" + row["request_id"]
    access = s.privacy.app.state.rights_access
    original = access.call

    def lost(*args, **kwargs):
        original(*args, **kwargs)
        raise HTTPException(503)

    access.call = lost
    assert (
        s.privacy.client.post(
            path + "/execute", headers=headers(s.officer, "stable", row["version"])
        ).status_code
        == 503
    )
    with Session(s.privacy.app.state.engine) as session, session.begin():
        owner = session.get(SubjectRequest, row["request_id"]).assignee_id
        scrub(session, owner)
    replacement = token(uuid4(), ("privacy_officer",), amr=["mfa"])
    pending = s.privacy.client.get(path, headers=s.auth).json()
    assert pending["status"] == "applying" and pending["assignee_id"] is None
    claimed = s.privacy.client.post(
        path + "/claim", headers=headers(replacement, "recover", pending["version"])
    )
    assert claimed.status_code == 200, claimed.text
    access.call = original
    finished = s.privacy.client.post(
        path + "/execute", headers=headers(replacement, "stable", row["version"])
    )
    assert finished.status_code == 200, finished.text
    assert finished.json()["status"] == "completed"
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["version"]
        == profile["version"] + 1
    )


def test_source_version_conflict_releases_adjudication(setup):
    s = setup
    row, profile = correction_request(s)
    updated = s.candidate.client.put(
        "/v1/candidates/me",
        json=dict(
            display_name="Candidate newer change", specialization="backend", declared_grade="middle"
        ),
        headers=headers(s.auth, "newer", profile["version"]),
    )
    assert updated.status_code == 200, updated.text
    path = "/v1/data-subject-requests/" + row["request_id"]
    result = s.privacy.client.post(
        path + "/execute", headers=headers(s.officer, "outdated", row["version"])
    )
    assert result.status_code == 409
    pending = s.privacy.client.get(path, headers=s.auth).json()
    assert pending["status"] == "in_review"
    assert "execution" not in pending["data"]
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["display_name"]
        == "Candidate newer change"
    )
