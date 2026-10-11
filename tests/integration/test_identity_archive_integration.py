"""Real signed owner boundaries with a fake Keycloak HTTP source."""

import base64
import json
from io import BytesIO

from reverse_hr.coordination.privacy_request_exchange import RightsAccess
from reverse_hr.platform.settings import SERVICES
from reverse_hr.services.identity.identity_export import KeycloakIdentityExport
from tests.integration.test_achievements_integration import signatures as signatures_fixture
from tests.services.identity.test_identity_export import configuration
from tests.services.privacy.test_privacy_archives import finish, start
from tests.services.privacy.test_privacy_subject_requests import setup as rights_setup

setup = rights_setup
signatures = signatures_fixture


class KeycloakTransport:
    def __init__(self, subject):
        self.subject = subject
        self.available = True

    def open(self, request, *, timeout):
        if not self.available:
            raise OSError("Fake source unavailable")
        if request.full_url.endswith("/token"):
            data = dict(access_token="SYNTHETIC", token_type="Bearer", expires_in=300)
        elif request.full_url.endswith("/credentials"):
            data = [dict(id="own-credential", type="otp", secretData="OMIT-SECRET")]
        else:
            data = dict(id=str(self.subject), username="own-user", email="own@example.test")
        response = BytesIO(json.dumps(data).encode())
        response.status = 200
        response.headers = {}
        return response


def wire(s, service, signatures, tmp_path):
    for owner in SERVICES:
        target = s.targets.get(owner)
        if target is None:
            target = service(owner)
            s.targets[owner] = target
        access = RightsAccess(target.app.state.settings)
        access._signatures, access._send = signatures[owner], s.sender
        target.app.state.rights_access = access
    instance = KeycloakIdentityExport(configuration(tmp_path))
    instance.opener = KeycloakTransport(s.candidate_id)
    s.targets["identity"].app.state.engine.identity_export_provider = instance
    s.privacy.app.state.settings.identity_export_enabled = True
    return instance


def test_all_seventeen_signed_owners_include_configured_identity(
    setup, service, signatures, tmp_path
):
    s = setup
    wire(s, service, signatures, tmp_path)
    row, path = start(s, None)
    archive = finish(s, path)
    assert archive["manifest"]["complete"] is True
    assert set(archive["manifest"]["sources"]) == set(SERVICES)
    cursor, records = None, []
    while True:
        response = s.privacy.client.get(
            path + "/pages",
            params={"cursor": cursor} if cursor else {},
            headers=s.auth,
        )
        assert response.status_code == 200, response.text
        page = response.json()
        if page["owner"] == "identity":
            for fragment in page["data"]["records"]:
                records.append(json.loads(base64.b64decode(fragment["base64"])))
        cursor = response.json()["next_cursor"]
        if not cursor:
            break
    assert {record["table"] for record in records} == {
        "keycloak_account",
        "keycloak_credential_metadata",
    }
    assert "OMIT-SECRET" not in json.dumps(records)
    current = s.privacy.client.get(
        "/v1/data-subject-requests/" + row["request_id"],
        headers=s.auth,
    ).json()
    assert current["status"] == "completed"


def test_configured_unavailable_identity_never_returns_ready_archive(
    setup, service, signatures, tmp_path
):
    s = setup
    instance = wire(s, service, signatures, tmp_path)
    instance.opener.available = False
    _, path = start(s, "identity")
    response = s.privacy.client.post(path + "/advance", headers=s.auth)
    assert response.status_code == 503
    archive = s.privacy.client.get(path, headers=s.auth).json()
    assert archive["status"] == "building" and archive["manifest"]["complete"] is False
