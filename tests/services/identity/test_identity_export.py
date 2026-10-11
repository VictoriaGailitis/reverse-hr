"""Identity export transport is entirely fake; no real key/user/provider access."""

import json
from io import BytesIO
from types import SimpleNamespace
from urllib.parse import parse_qs
from uuid import uuid4

import pytest
from fastapi import HTTPException

from reverse_hr.services.identity.identity_export import MAX_RESPONSE, KeycloakIdentityExport


class Response(BytesIO):
    status = 200
    headers = {}


class Transport:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def open(self, request, *, timeout):
        self.calls.append((request, timeout))
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        raw = result if isinstance(result, bytes) else json.dumps(result).encode()
        return Response(raw)


def configuration(tmp_path, **changes):
    key = tmp_path / "service.key"
    key.write_text("PRIVATE-SERVICE-KEY")
    return SimpleNamespace(
        **dict(
            identity_export_enabled=True,
            identity_export_origin="https://identity.example.invalid",
            identity_export_realm="reverse-hr",
            identity_export_client_id="privacy-export",
            identity_export_key_file=str(key),
            identity_export_timeout_seconds=5,
            identity_export_trusted_local=False,
            identity_export_attribute_names=["locale"],
        )
        | changes
    )


def provider(tmp_path, responses, **changes):
    instance = KeycloakIdentityExport(configuration(tmp_path, **changes))
    instance.opener = Transport(responses)
    return instance


def token(**changes):
    return dict(access_token="SERVICE-TOKEN", token_type="Bearer", expires_in=300) | changes


def test_own_projection_excludes_all_secrets_and_third_party_fields(tmp_path):
    subject = uuid4()
    account = dict(
        id=str(subject),
        username="candidate",
        email="candidate@example.invalid",
        firstName="Name",
        lastName="Surname",
        emailVerified=True,
        enabled=True,
        createdTimestamp=123,
        attributes={"locale": ["ru"], "token": ["PRIVATE-TOKEN"]},
        credentials=[{"secretData": "PRIVATE-PASSWORD"}],
        federatedIdentities=[{"userId": "OTHER"}],
        access={"manage": True},
        groups=["OTHER-GROUP"],
    )
    credentials = [
        dict(
            id="credential-id",
            type="otp",
            userLabel="Authenticator",
            createdDate=456,
            secretData="PRIVATE-OTP",
            credentialData="PRIVATE-HASH",
            value="SECRET",
        )
    ]
    instance = provider(tmp_path, [token(), account, credentials, account, credentials])
    records = instance.records(subject)
    rendered = json.dumps(records)
    assert "PRIVATE" not in rendered and "SECRET" not in rendered and "OTHER" not in rendered
    assert records[0]["data"]["attributes"] == {"locale": ["ru"]}
    assert records[1]["data"] == dict(
        id="credential-id", type="otp", userLabel="Authenticator", createdDate=456
    )
    assert instance.records(subject) == records
    assert len(instance.opener.calls) == 5  # Token cached, source never cached.
    requests = [call[0] for call in instance.opener.calls]
    assert requests[0].full_url.endswith("/realms/reverse-hr/protocol/openid-connect/token")
    assert parse_qs(requests[0].data.decode()) == dict(
        grant_type=["client_credentials"],
        client_id=["privacy-export"],
        client_secret=["PRIVATE-SERVICE-KEY"],
    )
    assert all(str(subject) in request.full_url for request in requests[1:])
    assert all(request.get_method() == "GET" for request in requests[1:])


@pytest.mark.parametrize(
    "origin,trusted",
    [
        ("http://public.example.invalid", True),
        ("http://localhost", False),
        ("https://user:password@example.invalid", False),
        ("https://example.invalid/search?q=x", False),
        ("https://example.invalid/realm", False),
        ("https://example.invalid/#x", False),
    ],
)
def test_configured_origin_rejects_untrusted_destinations(tmp_path, origin, trusted):
    with pytest.raises(ValueError):
        KeycloakIdentityExport(
            configuration(
                tmp_path, identity_export_origin=origin, identity_export_trusted_local=trusted
            )
        )


def test_lazy_constructor_and_explicit_local_origin(tmp_path):
    instance = KeycloakIdentityExport(
        configuration(
            tmp_path,
            identity_export_origin="http://keycloak:8080",
            identity_export_trusted_local=True,
            identity_export_key_file=str(tmp_path / "absent"),
        )
    )
    with pytest.raises(HTTPException) as error:
        instance.records(uuid4())
    assert error.value.status_code == 503
    with pytest.raises(ValueError):
        KeycloakIdentityExport(configuration(tmp_path, identity_export_enabled=False))


@pytest.mark.parametrize(
    "bad_account",
    [
        {},
        {"id": str(uuid4())},
        {"id": "not-a-uuid"},
        {"emailVerified": "true"},
    ],
)
def test_ownership_or_malformed_account_fails_closed(tmp_path, bad_account):
    subject = uuid4()
    account = {"id": str(subject)} | bad_account
    if not bad_account:
        account = {}
    instance = provider(tmp_path, [token(), account, []])
    with pytest.raises(HTTPException) as error:
        instance.records(subject)
    assert error.value.status_code == 503


@pytest.mark.parametrize(
    "response",
    [
        b'{"access_token":"first","access_token":"second","token_type":"Bearer","expires_in":300}',
        token(expires_in=True),
        token(access_token="bad\nheader"),
        b"x" * (MAX_RESPONSE + 1),
        RuntimeError("PRIVATE transport error"),
    ],
)
def test_bounded_token_json_and_transport_errors_do_not_leak(tmp_path, response):
    instance = provider(tmp_path, [response])
    with pytest.raises(HTTPException) as error:
        instance.records(uuid4())
    assert error.value.status_code == 503
    assert error.value.detail == "Identity source unavailable"


def test_expired_token_refetched_and_source_changes_are_not_cached(tmp_path, monkeypatch):
    subject = uuid4()
    now = [100.0]
    monkeypatch.setattr(
        "reverse_hr.services.identity.identity_export.time.monotonic", lambda: now[0]
    )
    instance = provider(
        tmp_path,
        [
            token(expires_in=10),
            {"id": str(subject), "email": "old"},
            [],
            token(),
            {"id": str(subject), "email": "new"},
            [],
        ],
    )
    assert instance.records(subject)[0]["data"]["email"] == "old"
    now[0] += 6
    assert instance.records(subject)[0]["data"]["email"] == "new"
    assert len(instance.opener.calls) == 6


@pytest.mark.parametrize(
    "credentials",
    [
        {},
        [{"id": "one", "type": "otp"}] * 2,
        [{"id": "one", "type": "otp", "createdDate": True}],
        [{"id": str(i), "type": "otp"} for i in range(65)],
    ],
)
def test_ambiguous_or_oversized_credential_metadata_fails_closed(tmp_path, credentials):
    subject = uuid4()
    instance = provider(tmp_path, [token(), {"id": str(subject)}, credentials])
    with pytest.raises(HTTPException) as error:
        instance.records(subject)
    assert error.value.status_code == 503


def test_sensitive_attribute_configuration_refused(tmp_path):
    with pytest.raises(ValueError):
        KeycloakIdentityExport(
            configuration(tmp_path, identity_export_attribute_names=["accessToken"])
        )


def test_unauthorized_source_invalidates_token_without_automatic_retry(tmp_path):
    from urllib.error import HTTPError

    subject = uuid4()
    instance = provider(
        tmp_path,
        [
            token(),
            HTTPError("https://fixed.invalid", 401, "Unauthorized", {}, None),
            token(access_token="NEW-TOKEN"),
            {"id": str(subject)},
            [],
        ],
    )
    with pytest.raises(HTTPException) as error:
        instance.records(subject)
    assert error.value.status_code == 503
    assert len(instance.opener.calls) == 2
    assert instance.records(subject)[0]["data"]["id"] == str(subject)
    assert instance.opener.calls[-1][0].get_header("Authorization") == "Bearer NEW-TOKEN"


def test_subject_path_injection_never_accesses_provider(tmp_path):
    instance = provider(tmp_path, [])
    with pytest.raises(HTTPException) as error:
        instance.records("../users?search=someone")
    assert error.value.status_code == 503
    assert not instance.opener.calls
