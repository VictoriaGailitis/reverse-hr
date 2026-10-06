"""Opt-in Keycloak tests: create and remove only a uniquely named temporary realm."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import struct
import time
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from uuid import uuid4

import httpx
import pytest

from reverse_hr.auth import TokenVerifier
from reverse_hr.settings import Settings

pytestmark = pytest.mark.skipif(
    not os.getenv("HR_TEST_KEYCLOAK_ADMIN_PASSWORD"), reason="Live Keycloak not configured"
)


class Forms(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.forms, self.current = [], None
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "form":
            self.current = {"action": attrs.get("action"), "inputs": {}}
            self.forms.append(self.current)
        elif tag == "input" and self.current is not None and attrs.get("name"):
            self.current["inputs"][attrs["name"]] = attrs.get("value", "")

    def handle_endtag(self, tag):
        if tag == "form":
            self.current = None


def otp(secret):
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(time.time()) // 30), hashlib.sha1).digest()
    offset = digest[-1] & 15
    return f"{(struct.unpack('>I', digest[offset : offset + 4])[0] & 0x7FFFFFFF) % 1000000:06d}"


@pytest.fixture(scope="module")
def live_realm():
    origin = os.getenv("HR_TEST_KEYCLOAK_URL", "http://localhost:8080").rstrip("/")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"localhost", "127.0.0.1"}
        or parsed.path
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
    ):
        pytest.fail("Keycloak test server must be a loopback HTTP origin", pytrace=False)
    client = httpx.Client(timeout=10, trust_env=False, follow_redirects=False)
    reply = client.post(
        origin + "/realms/master/protocol/openid-connect/token",
        data={
            "grant_type": "password",
            "client_id": "admin-cli",
            "username": os.getenv("HR_TEST_KEYCLOAK_ADMIN_USER", "local-admin"),
            "password": os.environ["HR_TEST_KEYCLOAK_ADMIN_PASSWORD"],
        },
    )
    if reply.status_code != 200:
        pytest.fail("Test Keycloak administrator authentication failed", pytrace=False)
    auth = {"Authorization": "Bearer " + reply.json()["access_token"]}
    config = json.loads(Path("infra/keycloak/realm.json").read_text())
    name = "hr-test-" + uuid4().hex
    config["realm"] = name
    created = False
    try:
        result = client.post(origin + "/admin/realms", headers=auth, json=config)
        if result.status_code != 201:
            pytest.fail("Temporary Keycloak realm import failed", pytrace=False)
        created = True
        yield origin, name, client, auth
    finally:
        if created:
            result = client.delete(origin + "/admin/realms/" + name, headers=auth)
            if result.status_code != 204:
                pytest.fail("Temporary Keycloak realm cleanup failed: " + name, pytrace=False)
        client.close()


def account(live_realm, role=None):
    origin, realm, client, auth = live_realm
    username, password = "synthetic-" + uuid4().hex, secrets.token_urlsafe(24) + "1aA"
    root = origin + "/admin/realms/" + realm
    response = client.post(
        root + "/users",
        headers=auth,
        json={
            "username": username,
            "email": username + "@reverse-hr.invalid",
            "emailVerified": True,
            "enabled": True,
            "firstName": "Synthetic",
            "lastName": "Test",
            "credentials": [{"type": "password", "value": password, "temporary": False}],
        },
    )
    if response.status_code != 201:
        pytest.fail("Synthetic test account creation failed", pytrace=False)
    user_id = response.headers["Location"].rsplit("/", 1)[1]
    if role:
        representation = client.get(root + "/roles/" + role, headers=auth)
        if representation.status_code != 200:
            pytest.fail("Privileged role lookup failed", pytrace=False)
        assigned = client.post(
            root + "/users/" + user_id + "/role-mappings/realm",
            headers=auth,
            json=[representation.json()],
        )
        if assigned.status_code != 204:
            pytest.fail("Synthetic test role assignment failed", pytrace=False)
    return username, password


def authorization(live_realm, username, password, secret=None, enroll=False):
    origin, realm, _, _ = live_realm
    issuer = origin + "/realms/" + realm
    redirect_uri = "http://localhost:3000/auth/callback"
    verifier, state = secrets.token_urlsafe(48), secrets.token_urlsafe(24)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )
    with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as browser:
        response = browser.get(
            issuer
            + "/protocol/openid-connect/auth?"
            + urlencode(
                {
                    "client_id": "reverse-hr-web",
                    "response_type": "code",
                    "scope": "openid email profile",
                    "redirect_uri": redirect_uri,
                    "state": state,
                    "code_challenge": challenge,
                    "code_challenge_method": "S256",
                }
            )
        )
        for _ in range(12):
            if response.is_redirect:
                location = response.headers["Location"]
                if location.startswith(redirect_uri + "?"):
                    params = parse_qs(urlsplit(location).query)
                    if params.get("state") != [state] or "code" not in params:
                        pytest.fail("Authorization callback binding failed", pytrace=False)
                    token = browser.post(
                        issuer + "/protocol/openid-connect/token",
                        data={
                            "grant_type": "authorization_code",
                            "client_id": "reverse-hr-web",
                            "redirect_uri": redirect_uri,
                            "code": params["code"][0],
                            "code_verifier": verifier,
                        },
                    )
                    if token.status_code != 200:
                        pytest.fail("PKCE code exchange failed", pytrace=False)
                    return token.json()["access_token"], secret
                if not location.startswith(issuer + "/"):
                    pytest.fail("Unexpected authentication redirect", pytrace=False)
                response = browser.get(location)
                continue
            forms = Forms(response.text).forms
            form = next(
                (
                    form
                    for form in forms
                    if any(field in form["inputs"] for field in ("username", "totpSecret", "otp"))
                ),
                None,
            )
            if (
                response.status_code != 200
                or form is None
                or not form["action"]
                or not form["action"].startswith(issuer + "/")
            ):
                pytest.fail("Unexpected authentication form", pytrace=False)
            fields = form["inputs"]
            if "username" in fields:
                fields.update(username=username, password=password)
            elif "totpSecret" in fields:
                if not enroll:
                    pytest.fail("Unexpected OTP enrollment requirement", pytrace=False)
                secret = fields["totpSecret"]
                fields.update(totp=otp(secret), userLabel="Synthetic test device", save="Save")
            else:
                if not secret:
                    pytest.fail("OTP required without test credential", pytrace=False)
                fields["otp"] = otp(secret)
            response = browser.post(form["action"], data=fields)
    pytest.fail("Authentication exceeded bounded flow steps", pytrace=False)


def verify(live_realm, token):
    origin, realm, _, _ = live_realm
    issuer = origin + "/realms/" + realm
    return TokenVerifier(
        Settings(oidc_issuer=issuer, oidc_jwks_url=issuer + "/protocol/openid-connect/certs")
    ).verify(token)


def test_live_candidate_token_matches_backend_without_mfa(live_realm):
    username, password = account(live_realm)
    token, _ = authorization(live_realm, username, password)
    principal = verify(live_realm, token)
    assert principal.roles == frozenset({"candidate"})
    assert not principal.mfa


def test_live_privileged_role_enrolls_otp_and_emits_real_mfa(live_realm):
    username, password = account(live_realm, "company_moderator")
    _, secret = authorization(live_realm, username, password, enroll=True)
    assert secret is not None
    token, _ = authorization(live_realm, username, password, secret=secret)
    principal = verify(live_realm, token)
    principal.require("company_moderator", mfa=True)


def test_live_password_grant_is_disabled(live_realm):
    origin, realm, client, _ = live_realm
    response = client.post(
        origin + "/realms/" + realm + "/protocol/openid-connect/token",
        data={
            "client_id": "reverse-hr-web",
            "grant_type": "password",
            "username": "synthetic-invalid",
            "password": "synthetic-invalid",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "unauthorized_client"
