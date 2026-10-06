import json
from pathlib import Path

import pytest
import yaml

from reverse_hr.auth import TokenVerifier
from reverse_hr.settings import Settings


@pytest.fixture
def realm():
    return json.loads(Path("infra/keycloak/realm.json").read_text())


def test_self_registration_never_grants_privileged_roles(realm):
    roles = {role["name"]: role for role in realm["roles"]["realm"]}

    def inherited(name):
        result = {name}
        for child in roles[name].get("composites", {}).get("realm", []):
            result |= inherited(child)
        return result

    defaults = set().union(*(inherited(name) for name in realm["defaultRoles"]))
    assert defaults == {"candidate"}
    for role in ("company_moderator", "assessment_reviewer", "content_admin", "technical_admin"):
        assert "requires_mfa" in inherited(role)
    assert "requires_mfa" not in inherited("employer")
    assert realm["verifyEmail"] and realm["resetPasswordAllowed"]
    assert not realm["duplicateEmailsAllowed"]


def test_otp_reference_can_only_be_emitted_by_real_otp_execution(realm):
    flows = {flow["alias"]: flow for flow in realm["authenticationFlows"]}
    configs = {config["alias"]: config["config"] for config in realm["authenticatorConfig"]}
    assert realm["browserFlow"] == "hr-browser"
    root = flows[realm["browserFlow"]]["authenticationExecutions"]
    assert root[0]["authenticator"] == "auth-username-password-form"
    assert root[0]["requirement"] == "REQUIRED"
    assert [step["requirement"] for step in root[1:]] == ["CONDITIONAL", "CONDITIONAL"]
    assert not any(step.get("authenticator") == "auth-cookie" for step in root)
    for flow in flows.values():
        for step in flow["authenticationExecutions"]:
            config = configs.get(step.get("authenticatorConfig"), {})
            if config.get("default.reference.value") in {"otp", "mfa"}:
                assert step["authenticator"] == "auth-otp-form"
                assert step["requirement"] == "REQUIRED"
                assert int(config["default.reference.maxAge"]) <= 900
    required = flows["hr-required-mfa"]["authenticationExecutions"]
    assert configs[required[0]["authenticatorConfig"]] == {
        "condUserRole": "requires_mfa",
        "negate": "false",
    }
    optional = flows["hr-enrolled-mfa"]["authenticationExecutions"]
    assert configs[optional[0]["authenticatorConfig"]]["negate"] == "true"
    assert optional[1]["authenticator"] == "conditional-user-configured"


def test_pkce_and_token_contract_and_local_mail_boundary(realm):
    client = realm["clients"][0]
    assert client["publicClient"] and client["standardFlowEnabled"]
    assert not client["directAccessGrantsEnabled"] and not client["implicitFlowEnabled"]
    assert not client["serviceAccountsEnabled"] and not client["fullScopeAllowed"]
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert "*" not in "".join(client["redirectUris"])
    assert "email" in client["defaultClientScopes"] and "roles" in client["defaultClientScopes"]
    mappers = {mapper["protocolMapper"]: mapper for mapper in client["protocolMappers"]}
    assert mappers["oidc-amr-mapper"]["config"]["access.token.claim"] == "true"
    assert not any(
        mapper["protocolMapper"] == "oidc-hardcoded-claim-mapper"
        for mapper in client["protocolMappers"]
    )
    assert (
        mappers["oidc-audience-mapper"]["config"]["included.custom.audience"]
        == Settings().oidc_audience
    )
    compose = yaml.safe_load(Path("compose.yaml").read_text())
    assert realm["smtpServer"]["host"] == "mailpit"
    assert compose["services"]["mailpit"]["networks"] == ["backend"]
    assert compose["networks"]["backend"]["internal"]
    assert compose["services"]["mailpit"]["ports"] == ["127.0.0.1:8025:8025"]
    assert realm["accessTokenLifespan"] <= 300 and realm["bruteForceProtected"]
    assert realm["revokeRefreshToken"] and realm["refreshTokenMaxReuse"] == 0


def test_malformed_amr_is_rejected(token, keys):
    from fastapi import HTTPException

    verifier = TokenVerifier(Settings())
    verifier.jwks.fetch_data = lambda: {"keys": [keys[1]]}
    for amr in ({"otp": True}, ["otp", 1], [None]):
        auth = token(amr=amr)["Authorization"].removeprefix("Bearer ")
        with pytest.raises(HTTPException) as error:
            verifier.verify(auth)
        assert error.value.status_code == 401
    for amr, expected in ((["pwd"], False), (["pwd", "otp"], True)):
        auth = token(amr=amr)["Authorization"].removeprefix("Bearer ")
        assert verifier.verify(auth).mfa == expected
