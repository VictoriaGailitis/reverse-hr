import base64
import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.platform.settings import Settings
from reverse_hr.protocols.processing_access import (
    REQUEST_CONTEXT,
    RESPONSE_CONTEXT,
    ProcessingAccess,
    ProcessingRequest,
    ProcessingStatus,
)
from reverse_hr.services.candidate.domain.candidate import CandidateProfile
from reverse_hr.services.employer.domain.employer import Membership
from reverse_hr.services.privacy.domain.privacy import ProcessingNonce
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, sign
from tests.shared.test_access import PROFILE, headers


@pytest.fixture
def signing():
    private = {
        service: Ed25519PrivateKey.generate()
        for service in (
            "candidate",
            "employer",
            "privacy",
            "assessment",
            "coding-workspace",
            "code-runner",
        )
    }
    public = {
        service: base64.b64encode(
            key.public_key().public_bytes(
                serialization.Encoding.Raw, serialization.PublicFormat.Raw
            )
        ).decode()
        for service, key in private.items()
    }
    return {
        service: Signatures(
            service,
            key.private_bytes(
                serialization.Encoding.Raw,
                serialization.PrivateFormat.Raw,
                serialization.NoEncryption(),
            ),
            public,
        )
        for service, key in private.items()
    }


def connect_access(service_name, privacy, signing):
    access = ProcessingAccess(Settings(service_name=service_name))
    access._signatures = signing[service_name]

    def send(body, signature):
        response = privacy.client.post(
            "/internal/v1/processing-status",
            content=body,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise HTTPException(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    access.send = send
    return access


def test_signed_restriction_blocks_candidate_before_event_delivery(service, token, signing):
    privacy, candidate = service("privacy"), service("candidate")
    privacy.app.state.privacy_signatures = signing["privacy"]
    candidate.app.state.processing_access = connect_access("candidate", privacy, signing)
    subject = uuid4()
    auth = token(subject)
    assert (
        candidate.client.post("/v1/candidates/me", json=PROFILE, headers=headers(auth)).status_code
        == 201
    )
    assert privacy.client.post("/v1/deletion-requests", headers=headers(auth)).status_code == 202
    for key in ("command-1", "fresh"):
        assert (
            candidate.client.post(
                "/v1/candidates/me", json=PROFILE, headers=headers(auth, key)
            ).status_code
            == 409
        )
    assert candidate.client.get("/v1/candidates/me", headers=auth).status_code == 409
    # No consumer ran: restrictions stop access while the physical profile still exists.
    with Session(candidate.app.state.engine) as session:
        assert session.get(CandidateProfile, str(subject)) is not None


def test_signed_restriction_blocks_membership_target_before_event(service, token, signing):
    privacy, employer = service("privacy"), service("employer")
    privacy.app.state.privacy_signatures = signing["privacy"]
    employer.app.state.processing_access = connect_access("employer", privacy, signing)
    owner, employee = uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", json={"name": "Synthetic"}, headers=headers(auth)
    ).json()
    assert (
        privacy.client.post("/v1/deletion-requests", headers=headers(token(employee))).status_code
        == 202
    )
    path = f"/v1/organizations/{org['organization_id']}/members"
    assert (
        employer.client.post(
            path,
            json={"subject": str(employee), "role": "recruiter"},
            headers=headers(auth, "add", 1),
        ).status_code
        == 409
    )
    with Session(employer.app.state.engine) as session:
        assert not list(
            session.scalars(select(Membership).where(Membership.subject == str(employee)))
        )
    assert (
        privacy.client.post("/v1/deletion-requests", headers=headers(token(owner))).status_code
        == 202
    )
    assert employer.client.get("/v1/organizations", headers=auth).status_code == 409


def test_privacy_service_auth_replay_timestamp_and_nonce_expiry(service, signing):
    privacy = service("privacy")
    privacy.app.state.privacy_signatures = signing["privacy"]
    request = ProcessingRequest(
        candidate_id=uuid4(), nonce=uuid4(), requester="candidate", issued_at=datetime.now(UTC)
    )

    def call(model, signature=None):
        signature = signature or sign(signing["candidate"], REQUEST_CONTEXT, model)
        return privacy.client.post(
            "/internal/v1/processing-status",
            content=canonical(model),
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )

    response = call(request)
    assert response.status_code == 200 and response.json()["allowed"] is True
    assert response.headers["Cache-Control"] == "no-store"
    assert call(request).status_code == 401
    changed = request.model_copy(update={"candidate_id": uuid4()})
    assert call(changed, sign(signing["candidate"], REQUEST_CONTEXT, request)).status_code == 401
    assert (
        call(
            request.model_copy(
                update={"nonce": uuid4(), "issued_at": datetime.now(UTC) - timedelta(minutes=1)}
            )
        ).status_code
        == 401
    )
    assert (
        call(
            request.model_copy(
                update={"nonce": uuid4(), "issued_at": datetime.now(UTC) + timedelta(minutes=1)}
            )
        ).status_code
        == 401
    )
    assert (
        call(request.model_copy(update={"nonce": uuid4(), "issued_at": datetime.now()})).status_code
        == 401
    )
    with Session(privacy.app.state.engine) as session, session.begin():
        nonce = session.get(ProcessingNonce, ("candidate", str(request.nonce)))
        nonce.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert call(request.model_copy(update={"nonce": uuid4()})).status_code == 200
    with Session(privacy.app.state.engine) as session:
        assert session.get(ProcessingNonce, ("candidate", str(request.nonce))) is None


@pytest.mark.parametrize(
    "failure",
    [
        "timeout",
        "signature",
        "nonce",
        "subject",
        "requester",
        "expired",
        "event_context",
        "oversized",
        "invalid_allowed",
    ],
)
def test_untrusted_or_unavailable_privacy_fails_closed(signing, failure):
    access = ProcessingAccess(Settings(service_name="candidate"))
    access._signatures = signing["candidate"]

    def send(raw, signature):
        if failure == "timeout":
            raise TimeoutError("private network detail")
        request = ProcessingRequest.model_validate_json(raw)
        status = ProcessingStatus(**request.model_dump(), allowed=True)
        changes = {
            "nonce": {"nonce": uuid4()},
            "subject": {"candidate_id": uuid4()},
            "requester": {"requester": "employer"},
            "expired": {"issued_at": datetime.now(UTC) - timedelta(minutes=1)},
            "invalid_allowed": {"allowed": "true"},
        }
        if failure == "invalid_allowed":
            values = status.model_dump(mode="json") | {"allowed": "true"}
            raw = json.dumps(values, sort_keys=True, separators=(",", ":")).encode()
            signed = base64.b64encode(
                signing["privacy"].private.sign(RESPONSE_CONTEXT + raw)
            ).decode()
            return raw, signed
        status = status.model_copy(update=changes.get(failure, {}))
        signed = sign(
            signing["privacy"],
            REQUEST_CONTEXT if failure == "event_context" else RESPONSE_CONTEXT,
            status,
        )
        if failure == "signature":
            signed = sign(signing["employer"], RESPONSE_CONTEXT, status)
        return b"x" * 4097 if failure == "oversized" else canonical(status), signed

    access.send = send
    with pytest.raises(HTTPException) as exc:
        access.check(uuid4())
    assert exc.value.status_code == 503


def test_unavailable_privacy_prevents_profile_write_and_replay(service, token):
    candidate = service("candidate")
    subject = uuid4()
    auth = token(subject)
    assert (
        candidate.client.post("/v1/candidates/me", json=PROFILE, headers=headers(auth)).status_code
        == 201
    )

    def unavailable(_):
        raise HTTPException(503)

    candidate.app.state.processing_access = SimpleNamespace(check=unavailable)
    assert (
        candidate.client.post("/v1/candidates/me", json=PROFILE, headers=headers(auth)).status_code
        == 503
    )
    assert candidate.client.get("/v1/candidates/me", headers=auth).status_code == 503


@pytest.mark.parametrize(
    "url",
    [
        "file:///tmp/x",
        "http://user:pass@privacy",
        "http://privacy/path",
        "http://privacy?x=1",
        "http://privacy#x",
    ],
)
def test_privacy_origin_is_fixed_and_has_no_credentials(url):
    with pytest.raises(ValueError):
        Settings(privacy_api_url=url)


@pytest.mark.parametrize("backend", ["sqlite", "postgres"])
def test_real_http_signed_privacy_status(keys, token, signing, tmp_path, backend):
    import os
    import socket
    import time
    from threading import Thread

    import uvicorn
    from alembic import command
    from fastapi.testclient import TestClient

    from reverse_hr.platform.app import create_app
    from reverse_hr.platform.migrate import migration_config

    if not os.getenv("HR_TEST_ENABLE_HTTP"):
        pytest.skip("Live HTTP test not enabled")
    if backend == "sqlite":
        url = f"sqlite:///{tmp_path}/privacy.db"
        employer_url = f"sqlite:///{tmp_path}/employer.db"
    else:
        url = os.getenv("HR_TEST_PRIVACY_POSTGRES_URL")
        employer_url = os.getenv("HR_TEST_EMPLOYER_DATABASE_URL")
        if not url or not employer_url:
            pytest.skip("Privacy/Employer PostgreSQL not configured")
    settings = Settings(service_name="privacy", database_url=url)
    command.upgrade(migration_config(settings), "head")
    privacy_app = create_app(settings)
    privacy_app.state.privacy_signatures = signing["privacy"]
    redirects = {"enabled": False, "target_hits": 0}

    @privacy_app.middleware("http")
    async def redirect_when_requested(request, call_next):
        if redirects["enabled"] and request.url.path == "/internal/v1/processing-status":
            from fastapi.responses import RedirectResponse

            return RedirectResponse("/unexpected-redirect", status_code=307)
        return await call_next(request)

    @privacy_app.post("/unexpected-redirect")
    def redirected_target():
        redirects["target_hits"] += 1
        return {"allowed": True}

    privacy_app.state.token_verifier.jwks.fetch_data = lambda: {"keys": [keys[1]]}
    # Bind first to avoid choosing an occupied port. No persistent local server remains.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(privacy_app, access_log=False, log_level="critical", lifespan="off")
    )
    thread = Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 5
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert server.started
        for name in ("candidate", "employer"):
            access = ProcessingAccess(
                Settings(
                    service_name=name, privacy_api_url=f"http://127.0.0.1:{sock.getsockname()[1]}"
                )
            )
            access._signatures = signing[name]
            subject = uuid4()
            access.check(subject)
            with TestClient(privacy_app) as client:
                assert (
                    client.post(
                        "/v1/deletion-requests", headers=headers(token(subject))
                    ).status_code
                    == 202
                )
            with pytest.raises(HTTPException) as exc:
                access.check(subject)
            assert exc.value.status_code == 409
        # Exercise third-party responses with real Employer/Privacy PostgreSQL
        # and the actual signed HTTP client, without running deletion consumers.
        employer_settings = Settings(
            service_name="employer",
            database_url=employer_url,
            privacy_api_url=f"http://127.0.0.1:{sock.getsockname()[1]}",
        )
        command.upgrade(migration_config(employer_settings), "head")
        employer_app = create_app(employer_settings)
        employer_app.state.token_verifier.jwks.fetch_data = lambda: {"keys": [keys[1]]}
        employer_app.state.processing_access._signatures = signing["employer"]
        owner, employee, reviewer = uuid4(), uuid4(), uuid4()
        auth = token(owner, ("employer",))
        with TestClient(employer_app) as employer_client, TestClient(privacy_app) as privacy_client:
            org = employer_client.post(
                "/v1/organizations", json={"name": "Synthetic"}, headers=headers(auth)
            ).json()
            path = f"/v1/organizations/{org['organization_id']}"
            assert (
                employer_client.post(
                    path + "/members",
                    json={"subject": str(employee), "role": "recruiter"},
                    headers=headers(auth, "employee", 1),
                ).status_code
                == 201
            )
            assert (
                employer_client.post(
                    path + "/verification",
                    json={"status": "verified", "reason": "Synthetic"},
                    headers=headers(
                        token(reviewer, ("company_moderator",), amr=["mfa"]), "verify", 2
                    ),
                ).status_code
                == 200
            )
            assert len(employer_client.get(path + "/members", headers=auth).json()) == 2
            for subject in (employee, reviewer):
                assert (
                    privacy_client.post(
                        "/v1/deletion-requests", headers=headers(token(subject))
                    ).status_code
                    == 202
                )
            members = employer_client.get(path + "/members", headers=auth)
            assert members.status_code == 200 and [row["subject"] for row in members.json()] == [
                str(owner)
            ]
            current = employer_client.get(path, headers=auth)
            assert current.status_code == 200 and current.json()["verified_by"] is None
            history = employer_client.get(path + "/verification-history", headers=auth)
            assert history.status_code == 200 and history.json() == []
        redirects["enabled"] = True
        with pytest.raises(HTTPException) as exc:
            access.check(uuid4())
        assert exc.value.status_code == 503
        assert redirects["target_hits"] == 0
    finally:
        server.should_exit = True
        thread.join(timeout=5)
        sock.close()
        privacy_app.state.engine.dispose()
    assert not thread.is_alive()


def test_employer_hides_member_before_cleanup_and_denies_saved_revoke(service, token, signing):
    from reverse_hr.services.employer.domain.employer import Organization

    privacy, employer = service("privacy"), service("employer")
    privacy.app.state.privacy_signatures = signing["privacy"]
    employer.app.state.processing_access = connect_access("employer", privacy, signing)
    owner, employee, colleague = uuid4(), uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", json={"name": "Synthetic"}, headers=headers(auth)
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    employee_member = employer.client.post(
        path + "/members",
        json={"subject": str(employee), "role": "recruiter"},
        headers=headers(auth, "employee", 1),
    ).json()
    assert (
        employer.client.post(
            path + "/members",
            json={"subject": str(colleague), "role": "technical_expert"},
            headers=headers(auth, "colleague", 2),
        ).status_code
        == 201
    )
    revoke = path + f"/members/{employee_member['membership_id']}/revoke"
    assert employer.client.post(revoke, headers=headers(auth, "revoke", 1)).status_code == 200
    before = employer.client.get(path + "/members", headers=auth)
    assert before.status_code == 200 and len(before.json()) == 3
    assert (
        privacy.client.post("/v1/deletion-requests", headers=headers(token(employee))).status_code
        == 202
    )
    result = employer.client.get(path + "/members", headers=auth)
    assert result.status_code == 200
    assert {row["subject"] for row in result.json()} == {str(owner), str(colleague)}
    assert employer.client.post(revoke, headers=headers(auth, "revoke", 1)).status_code == 409
    with Session(employer.app.state.engine) as session:
        assert session.get(Membership, employee_member["membership_id"]) is not None
        assert session.get(Organization, org["organization_id"]).version == 4


def test_employer_hides_reviewer_and_history_before_cleanup(service, token, signing):
    from reverse_hr.services.employer.domain.employer import Organization, VerificationDecision

    privacy, employer = service("privacy"), service("employer")
    privacy.app.state.privacy_signatures = signing["privacy"]
    employer.app.state.processing_access = connect_access("employer", privacy, signing)
    owner, reviewer, other = uuid4(), uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", json={"name": "Synthetic"}, headers=headers(auth)
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    for version, subject in [(1, other), (2, reviewer), (3, reviewer)]:
        assert (
            employer.client.post(
                path + "/verification",
                json={"status": "verified", "reason": "Synthetic decision"},
                headers=headers(
                    token(subject, ("company_moderator",), amr=["mfa"]),
                    f"verify-{version}",
                    version,
                ),
            ).status_code
            == 200
        )
    assert len(employer.client.get(path + "/verification-history", headers=auth).json()) == 3
    assert (
        privacy.client.post("/v1/deletion-requests", headers=headers(token(reviewer))).status_code
        == 202
    )
    current = employer.client.get(path, headers=auth)
    assert current.status_code == 200
    assert current.json()["verified_by"] is None and current.json()["verification_reason"] is None
    listed = employer.client.get("/v1/organizations", headers=auth)
    assert listed.status_code == 200 and listed.json()[0]["verified_by"] is None
    history = employer.client.get(path + "/verification-history", headers=auth)
    assert history.status_code == 200 and len(history.json()) == 1
    assert history.json()[0]["reviewer_id"] == str(other)
    with Session(employer.app.state.engine) as session:
        assert session.get(Organization, org["organization_id"]).verified_by == str(reviewer)
        assert len(list(session.scalars(select(VerificationDecision)))) == 3


def test_third_party_privacy_failure_returns_no_partial_response_and_rolls_back(service, token):
    from reverse_hr.services.employer.domain.employer import Organization
    from reverse_hr.shared.db import IdempotencyRecord, Outbox

    employer = service("employer")
    owner, employee = uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", json={"name": "Synthetic"}, headers=headers(auth)
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    member = employer.client.post(
        path + "/members",
        json={"subject": str(employee), "role": "recruiter"},
        headers=headers(auth, "add", 1),
    ).json()

    def check(subject):
        if subject == employee:
            raise HTTPException(503)

    employer.app.state.processing_access = SimpleNamespace(check=check)
    result = employer.client.get(path + "/members", headers=auth)
    assert result.status_code == 503
    assert str(owner) not in result.text and str(employee) not in result.text
    revoke = path + f"/members/{member['membership_id']}/revoke"
    assert employer.client.post(revoke, headers=headers(auth, "revoke", 1)).status_code == 503
    with Session(employer.app.state.engine) as session:
        assert session.get(Membership, member["membership_id"]).status == "active"
        assert session.get(Organization, org["organization_id"]).version == 2
        assert not list(
            session.scalars(
                select(IdempotencyRecord).where(IdempotencyRecord.operation.like("revoke_member:%"))
            )
        )
        assert not [
            row
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "employer.membership_revoked.v1"
        ]


def test_reviewer_checks_are_deduplicated_only_within_one_request(service, token):
    employer = service("employer")
    owner, reviewer = uuid4(), uuid4()
    auth = token(owner, ("employer",))
    org = employer.client.post(
        "/v1/organizations", json={"name": "Synthetic"}, headers=headers(auth)
    ).json()
    path = f"/v1/organizations/{org['organization_id']}"
    for version in range(1, 4):
        assert (
            employer.client.post(
                path + "/verification",
                json={"status": "verified", "reason": "Synthetic"},
                headers=headers(
                    token(reviewer, ("company_moderator",), amr=["mfa"]), f"v-{version}", version
                ),
            ).status_code
            == 200
        )
    calls = []

    def check(subject):
        calls.append(subject)

    employer.app.state.processing_access = SimpleNamespace(check=check)
    for _ in range(2):
        assert employer.client.get(path + "/verification-history", headers=auth).status_code == 200
    assert calls.count(reviewer) == 2


def test_assessment_signed_admission_blocks_catalog_before_deletion_delivery(
    service, token, signing
):
    from tests.services.assessment.test_assessment_content import PACKAGE

    privacy, assessment = service("privacy"), service("assessment")
    privacy.app.state.privacy_signatures = signing["privacy"]
    assessment.app.state.processing_access = connect_access("assessment", privacy, signing)
    subject = uuid4()
    auth = token(subject, ("content_admin",), amr=["mfa"])
    body = {"name": "Synthetic family", "content": PACKAGE}
    response = assessment.client.post(
        "/v1/content-families", headers=headers(auth, "family"), json=body
    )
    assert response.status_code == 201
    path = f"/v1/content-versions/{response.json()['revision_id']}"
    assert assessment.client.get(path, headers=auth).status_code == 200
    assert (
        privacy.client.post("/v1/deletion-requests", headers=headers(token(subject))).status_code
        == 202
    )
    assert assessment.client.get(path, headers=auth).status_code == 409
    for key in ("family", "fresh"):
        assert (
            assessment.client.post(
                "/v1/content-families", headers=headers(auth, key), json=body
            ).status_code
            == 409
        )
