"""Actual signed service admission and immutable invitation replacement."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.services.hiring.domain.hiring import InvitationRevision, process_deletion_request
from tests.integration.test_matching_hiring import consent, invite
from tests.integration.test_matching_hiring import setup as setup
from tests.integration.test_matching_hiring import signatures as signatures
from tests.services.code_runner.test_code_runner import deletion
from tests.shared.test_access import headers


def terms(s, description="First role"):
    return dict(
        organization_id=s.organization_id,
        candidate_id=str(s.candidate_id),
        description=description,
        employer_contact="recruiter@example.test",
        salary=dict(tax_basis="gross", minimum=100000, maximum=200000),
    )


def test_draft_private_send_view_accept_and_history(setup):
    s = setup
    response = s.hiring.client.post(
        "/v1/invitation-drafts", json=terms(s), headers=headers(s.employer_auth, "draft")
    )
    assert response.status_code == 201, response.text
    item = response.json()
    path = "/v1/invitations/" + item["invitation_id"]
    assert s.hiring.client.get(path, headers=s.auth).status_code == 404
    assert s.hiring.client.get("/v1/invitations", headers=s.auth).json() == []
    assert (
        s.hiring.client.post(
            path + "/accept",
            json={"disclosure_consent_id": consent(s, "contact_disclosure")},
            headers=headers(s.auth, "draft-accept", 1),
        ).status_code
        == 404
    )
    edit = s.hiring.client.put(
        path + "/draft", json=terms(s, "Updated role"), headers=headers(s.employer_auth, "edit", 1)
    )
    assert edit.status_code == 200, edit.text
    sent = s.hiring.client.post(path + "/send", headers=headers(s.employer_auth, "send", 2))
    assert sent.status_code == 200, sent.text
    assert sent.json()["version"] == 3
    viewed = s.hiring.client.post(path + "/view", headers=headers(s.auth, "view", 3))
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["status"] == "viewed"
    disclosure = consent(s, "contact_disclosure")
    assert (
        s.hiring.client.post(
            path + "/accept",
            json={"disclosure_consent_id": disclosure},
            headers=headers(s.auth, "stale", 3),
        ).status_code
        == 409
    )
    accepted = s.hiring.client.post(
        path + "/accept",
        json={"disclosure_consent_id": disclosure},
        headers=headers(s.auth, "accept", 4),
    )
    assert accepted.status_code == 200, accepted.text
    history = s.hiring.client.get(path + "/history", headers=s.auth).json()
    assert [r["version"] for r in history] == [1, 2, 3]
    assert history[0]["terms"]["description"] == "First role"
    assert history[1]["terms"]["description"] == "Updated role"


def test_replacement_revokes_old_invitation_and_never_inherits_acceptance(setup):
    s = setup
    first = invite(s).json()
    path = "/v1/invitations/" + first["invitation_id"]
    disclosure = consent(s, "contact_disclosure")
    accepted = s.hiring.client.post(
        path + "/accept",
        json={"disclosure_consent_id": disclosure},
        headers=headers(s.auth, "accept", 1),
    )
    assert accepted.status_code == 200
    changed = s.hiring.client.post(
        path + "/revisions",
        json=terms(s, "New material conditions"),
        headers=headers(s.employer_auth, "revise", 2),
    )
    assert changed.status_code == 201, changed.text
    new = changed.json()
    assert new["invitation_id"] != first["invitation_id"] and new["status"] == "sent"
    assert s.hiring.client.get(path, headers=s.auth).json()["status"] == "revoked"
    assert s.hiring.client.get(path + "/contacts", headers=s.employer_auth).status_code == 409
    assert (
        s.hiring.client.post(
            path + "/accept",
            json={"disclosure_consent_id": disclosure},
            headers=headers(s.auth, "accept", 1),
        ).json()["status"]
        == "revoked"
    )
    new_path = "/v1/invitations/" + new["invitation_id"]
    assert s.hiring.client.get(new_path + "/contacts", headers=s.employer_auth).status_code == 409
    history = s.hiring.client.get(new_path + "/history", headers=s.auth).json()
    assert history[0]["predecessor_id"] == first["invitation_id"]
    replay = s.hiring.client.post(
        path + "/revisions",
        json=terms(s, "New material conditions"),
        headers=headers(s.employer_auth, "revise", 2),
    )
    assert replay.json()["invitation_id"] == new["invitation_id"]
    with Session(s.hiring.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate_id))
    with Session(s.hiring.app.state.engine) as session:
        assert list(session.scalars(select(InvitationRevision))) == []
