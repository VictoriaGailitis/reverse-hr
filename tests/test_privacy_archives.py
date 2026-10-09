"""Actual migrated owners, bounded signed pages and revocable immutable capture."""

import base64
import json
from datetime import UTC, datetime
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.orm import Session
from test_access import headers
from test_achievements_integration import signatures as signatures  # noqa: F401
from test_privacy_subject_requests import approve, submit  # noqa: F401
from test_privacy_subject_requests import setup as setup

from reverse_hr.domains.privacy_requests import RequestHistory
from reverse_hr.rights_export import SPECS, page


@pytest.mark.parametrize("owner", sorted(SPECS))
def test_export_allowlists_match_every_migrated_owner(service, signatures, owner):
    target = service(owner)
    with Session(target.app.state.engine) as session:
        result = page(session, owner, uuid4(), uuid4(), 3, signatures[owner])
        assert result["records"] == []
        assert result["complete"] is True


def start(s, domain="candidate"):
    row = approve(s, submit(s, domain=domain))
    path = "/v1/data-subject-requests/" + row["request_id"]
    response = s.privacy.client.post(path + "/archives", headers=s.auth)
    assert response.status_code == 201, response.text
    return row, path + "/archives/" + response.json()["archive_id"]


def finish(s, path):
    for _ in range(100):
        response = s.privacy.client.post(path + "/advance", headers=s.auth)
        assert response.status_code == 200, response.text
        if response.json()["status"] == "ready":
            return response.json()
    raise AssertionError("Archive never completed")


def test_archive_captured_immutable_then_withdrawn(setup):
    s = setup
    row, path = start(s)
    archived = finish(s, path)
    assert archived["manifest"]["complete"] is True
    assert "pages" not in archived["manifest"]
    assert len(json.dumps(archived["manifest"])) < 4000
    response = s.privacy.client.get(path + "/pages", headers=s.auth)
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    assert s.privacy.client.get(path + "/pages", headers=s.other).status_code == 404
    from reverse_hr.domains.candidate import CandidateProfile

    with Session(s.candidate.app.state.engine) as session, session.begin():
        profile = session.get(CandidateProfile, str(s.candidate_id))
        profile.display_name = "Updated after capture"
        profile.version += 1
    assert s.privacy.client.get(path + "/pages", headers=s.auth).json() == response.json()
    current = s.privacy.client.get(
        "/v1/data-subject-requests/" + row["request_id"], headers=s.auth
    ).json()
    withdrawal = s.privacy.client.post(
        "/v1/data-subject-requests/" + row["request_id"] + "/withdraw",
        headers=headers(s.auth, str(uuid4()), current["version"]),
    )
    assert withdrawal.status_code == 200, withdrawal.text
    assert s.privacy.client.get(path + "/pages", headers=s.auth).status_code == 404


def test_more_than_thousand_records_paged_and_cross_cursor_rejected(setup):
    s = setup
    with Session(s.privacy.app.state.engine) as session, session.begin():
        session.add_all(
            RequestHistory(
                history_id=str(uuid4()),
                request_id=str(uuid4()),
                candidate_id=str(s.candidate_id),
                actor_id=str(s.candidate_id),
                version=n,
                action="own_action",
                at=datetime.now(UTC),
                details={"note": "large " + str(n)},
            )
            for n in range(1005)
        )
    row, path = start(s, "privacy")
    archive = finish(s, path)
    assert archive["manifest"]["page_count"] > 10
    cursor = None
    count = 0
    while True:
        response = s.privacy.client.get(
            path + "/pages", params={"cursor": cursor} if cursor else {}, headers=s.auth
        )
        assert response.status_code == 200, response.text
        assert len(response.content) < 65536
        values = response.json()
        for part in values["data"]["records"]:
            record = json.loads(base64.b64decode(part["base64"]))
            if record["table"] == "privacy_request_history":
                count += 1
        cursor = values["next_cursor"]
        if cursor:
            bad = s.privacy.client.get(
                path + "/pages", params={"cursor": cursor + "x"}, headers=s.auth
            )
            assert bad.status_code == 401
        else:
            break
    assert count == 1008  # submit / claim / approve are captured too


def test_owner_cursor_source_revision_and_subject_binding(setup):
    s = setup
    with Session(s.privacy.app.state.engine) as session, session.begin():
        session.add_all(
            RequestHistory(
                history_id=str(uuid4()),
                request_id=str(uuid4()),
                candidate_id=str(s.candidate_id),
                actor_id=str(s.candidate_id),
                version=n,
                action="own_action",
                at=datetime.now(UTC),
                details={"note": "X" * 1000},
            )
            for n in range(120)
        )
    request = uuid4()
    with Session(s.privacy.app.state.engine) as session:
        first = page(
            session,
            "privacy",
            s.candidate_id,
            request,
            3,
            s.privacy.app.state.rights_access.signatures,
        )
        assert first["next_cursor"]
        with pytest.raises(HTTPException) as caught:
            page(
                session,
                "privacy",
                uuid4(),
                request,
                3,
                s.privacy.app.state.rights_access.signatures,
                first["next_cursor"],
            )
        assert caught.value.status_code == 401
        with pytest.raises(HTTPException) as caught:
            page(
                session,
                "privacy",
                s.candidate_id,
                request,
                4,
                s.privacy.app.state.rights_access.signatures,
                first["next_cursor"],
            )
        assert caught.value.status_code == 401
    with Session(s.privacy.app.state.engine) as session, session.begin():
        session.execute(update(RequestHistory).values(action="changed"))
    with Session(s.privacy.app.state.engine) as session:
        with pytest.raises(HTTPException) as caught:
            page(
                session,
                "privacy",
                s.candidate_id,
                request,
                3,
                s.privacy.app.state.rights_access.signatures,
                first["next_cursor"],
            )
        assert caught.value.status_code == 409


def test_identity_explicit_incomplete_never_completes_access(setup):
    s = setup
    row, path = start(s, "identity")
    archive = finish(s, path)
    assert archive["manifest"]["complete"] is False
    assert archive["manifest"]["capabilities"] == {"identity": "external_identity_unavailable"}
    request = s.privacy.client.get("/v1/data-subject-requests/" + row["request_id"], headers=s.auth)
    assert request.json()["status"] == "approved"


def test_manifest_detects_page_metadata_corruption(setup):
    from reverse_hr.domains.privacy_archives import ArchivePage

    s = setup
    _, path = start(s)
    archive = finish(s, path)
    with Session(s.privacy.app.state.engine) as session, session.begin():
        stored = session.get(ArchivePage, (archive["archive_id"], 0))
        stored.owner = "privacy"
    assert s.privacy.client.get(path + "/pages", headers=s.auth).status_code == 503
    assert s.privacy.client.get(path, headers=s.auth).status_code == 503


def test_source_change_abandon_and_retry_capture(setup):
    from reverse_hr.domains.candidate import CandidateProfile

    s = setup
    row, path = start(s)
    # Force multiple bounded pages through a large self-description record.
    from reverse_hr.domains.candidate_resume import Resume

    with Session(s.candidate.app.state.engine) as session, session.begin():
        session.add(
            Resume(
                candidate_id=str(s.candidate_id),
                fields={"summary": "X" * 70000},
                version=1,
                published=False,
                consent_id=None,
            )
        )
    assert s.privacy.client.post(path + "/advance", headers=s.auth).status_code == 200
    with Session(s.candidate.app.state.engine) as session, session.begin():
        session.get(CandidateProfile, str(s.candidate_id)).display_name = "Changed during capture"
    assert s.privacy.client.post(path + "/advance", headers=s.auth).status_code == 409
    assert s.privacy.client.post(path + "/abandon", headers=s.auth).status_code == 204
    response = s.privacy.client.post(
        "/v1/data-subject-requests/" + row["request_id"] + "/archives", headers=s.auth
    )
    assert response.status_code == 201
    finish(
        s,
        "/v1/data-subject-requests/"
        + row["request_id"]
        + "/archives/"
        + response.json()["archive_id"],
    )


def test_employer_only_account_can_request_its_own_data(setup, token):
    s = setup
    subject = uuid4()
    auth = token(subject, ("employer",))
    created = s.privacy.client.post(
        "/v1/data-subject-requests",
        json=dict(kind="access", domain="employer", reason="Own organization membership data"),
        headers=headers(auth, str(uuid4())),
    )
    assert created.status_code == 201, created.text
    assert created.json()["candidate_id"] == str(subject)
    assert (
        s.privacy.client.get(
            "/v1/data-subject-requests/" + created.json()["request_id"], headers=auth
        ).status_code
        == 200
    )
    assert (
        s.privacy.client.get(
            "/v1/data-subject-requests/" + created.json()["request_id"], headers=s.auth
        ).status_code
        == 404
    )


def test_employer_external_consents_only_and_own_revocation(setup, token):
    s = setup
    auth = token(uuid4(), ("employer",))
    assert set(s.privacy.client.get("/v1/consents/policies", headers=auth).json()) == {
        "external_service_notifications",
        "external_marketing_notifications",
    }
    row = s.privacy.client.post(
        "/v1/consents",
        json={"purpose": "external_service_notifications", "document_version": "demo-v1"},
        headers=headers(auth, str(uuid4())),
    )
    assert row.status_code == 201, row.text
    assert (
        s.privacy.client.post(
            "/v1/consents",
            json={"purpose": "assessment", "document_version": "demo-v1"},
            headers=headers(auth, str(uuid4())),
        ).status_code
        == 403
    )
    assert s.privacy.client.get("/v1/consents", headers=auth).json() == [row.json()]
    path = "/v1/consents/" + row.json()["consent_id"] + "/revoke"
    assert s.privacy.client.post(path, headers=headers(s.auth, str(uuid4()), 1)).status_code == 404
    assert s.privacy.client.post(path, headers=headers(auth, str(uuid4()), 1)).status_code == 200


def test_all_existing_owners_signed_capture_identity_remains_incomplete(setup, service, signatures):
    from reverse_hr.privacy_request_exchange import RightsAccess
    from reverse_hr.settings import SERVICES

    s = setup
    for owner in SERVICES:
        if owner == "identity":
            continue
        target = s.targets.get(owner)
        if target is None:
            target = service(owner)
            s.targets[owner] = target
        access = RightsAccess(target.app.state.settings)
        access._signatures, access._send = signatures[owner], s.sender
        target.app.state.rights_access = access
    row, path = start(s, None)
    archive = finish(s, path)
    assert archive["manifest"]["complete"] is False
    assert archive["manifest"]["capabilities"]["identity"] == "external_identity_unavailable"
    assert set(archive["manifest"]["sources"]) == set(SERVICES) - {"identity"}
    assert s.privacy.client.get(path + "/pages", headers=s.auth).status_code == 200
    assert (
        s.privacy.client.get(
            "/v1/data-subject-requests/" + row["request_id"], headers=s.auth
        ).json()["status"]
        == "approved"
    )


def test_archive_permission_withdrawn_during_owner_capture(setup):
    s = setup
    row, path = start(s)
    original = s.privacy.app.state.rights_access.call

    def interrupted(*args, **kwargs):
        data = original(*args, **kwargs)
        withdrawal = s.privacy.client.post(
            "/v1/data-subject-requests/" + row["request_id"] + "/withdraw",
            headers=headers(s.auth, str(uuid4()), row["version"]),
        )
        assert withdrawal.status_code == 200, withdrawal.text
        return data

    s.privacy.app.state.rights_access.call = interrupted
    assert s.privacy.client.post(path + "/advance", headers=s.auth).status_code == 404
    from sqlalchemy import select

    from reverse_hr.domains.privacy_archives import ArchivePage

    with Session(s.privacy.app.state.engine) as session:
        assert list(session.scalars(select(ArchivePage))) == []


def test_configured_identity_provider_signed_archive_complete(setup, service, signatures, tmp_path):
    from test_identity_export import provider
    from test_identity_export import token as provider_token

    from reverse_hr.privacy_request_exchange import RightsAccess

    s = setup
    identity = service("identity")
    s.targets["identity"] = identity
    account = {
        "id": str(s.candidate_id),
        "email": "own@example.invalid",
        "attributes": {"locale": ["ru"], "token": ["EXCLUDED"]},
    }
    instance = provider(tmp_path, [provider_token(), account, [], account, [], account, []])
    identity.app.state.engine.identity_export_provider = instance
    access = RightsAccess(identity.app.state.settings)
    access._signatures, access._send = signatures["identity"], s.sender
    identity.app.state.rights_access = access
    s.privacy.app.state.settings = s.privacy.app.state.settings.model_copy(
        update={"identity_export_enabled": True}
    )
    row, path = start(s, "identity")
    archive = finish(s, path)
    assert archive["manifest"]["complete"] is True
    assert archive["manifest"]["capabilities"] == {"identity": "paged"}
    assert (
        s.privacy.client.get(
            "/v1/data-subject-requests/" + row["request_id"], headers=s.auth
        ).json()["status"]
        == "completed"
    )
    downloaded = s.privacy.client.get(path + "/pages", headers=s.auth)
    assert downloaded.status_code == 200, downloaded.text
    records = downloaded.json()["data"]["records"]
    account = json.loads(base64.b64decode(records[0]["base64"]))
    assert account["table"] == "keycloak_account"
    assert account["data"]["email"] == "own@example.invalid"
    assert "EXCLUDED" not in str(account)


def test_capture_hash_is_bound_to_the_returned_stream(monkeypatch):
    from types import SimpleNamespace

    import reverse_hr.rights_export as exporting

    # The old before/capture/after implementation could label B with A's hash.
    streams = iter(
        [
            [{"table": "own", "key": "1", "data": {"value": "B"}}],
            [{"table": "own", "key": "1", "data": {"value": "A"}}],
        ]
    )
    monkeypatch.setattr(exporting, "records", lambda *_: iter(next(streams)))
    with pytest.raises(HTTPException) as caught:
        exporting.page(SimpleNamespace(), "candidate", uuid4(), uuid4(), 3, None)
    assert caught.value.status_code == 409
