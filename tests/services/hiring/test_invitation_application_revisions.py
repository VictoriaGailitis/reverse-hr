"""Material offer changes preserve the application but require fresh acceptance/grant."""

from sqlalchemy.orm import Session

from reverse_hr.services.privacy.domain.privacy import process_accepted_invitation
from tests.integration.test_matching_hiring import consent
from tests.services.hiring.test_hiring_dialogs import events
from tests.services.hiring.test_hiring_vacancies import (
    accept_application,
    app_action,
    apply,
)
from tests.services.hiring.test_hiring_vacancies import (
    published as published,
)
from tests.services.hiring.test_hiring_vacancies import (
    setup as setup,
)
from tests.services.hiring.test_hiring_vacancies import (
    signatures as signatures,
)
from tests.services.hiring.test_invitation_lifecycle import terms
from tests.shared.test_access import headers


def prepare_offer(s):
    application = accept_application(s, apply(s).json())
    path = "/v1/applications/" + application["application_id"]
    application = s.hiring.client.get(path, headers=s.employer_auth).json()
    for status in ("interview", "offer"):
        response = app_action(s, application, "status", body={"status": status})
        assert response.status_code == 200, response.text
        application = response.json()
    invitation = s.hiring.client.get(
        "/v1/invitations/" + application["invitation_id"], headers=s.employer_auth
    ).json()
    return application, invitation, path


def test_revised_terms_preserve_application_and_block_progress_until_new_grant(published):
    s = published
    application, invitation, app_path = prepare_offer(s)
    old_path = "/v1/invitations/" + invitation["invitation_id"]
    response = s.hiring.client.post(
        old_path + "/revisions",
        json=terms(s, "Revised offer terms"),
        headers=headers(s.employer_auth, "revise-app-offer", invitation["version"]),
    )
    assert response.status_code == 201, response.text
    new = response.json()
    application = s.hiring.client.get(app_path, headers=s.employer_auth).json()
    assert application["status"] == "offer" and application["invitation_id"] == new["invitation_id"]
    assert s.hiring.client.get(old_path + "/contacts", headers=s.employer_auth).status_code == 409
    assert app_action(s, application, "status", body={"status": "hired"}).status_code == 409
    new_path = "/v1/invitations/" + new["invitation_id"]
    assert (
        s.hiring.client.post(
            new_path + "/accept",
            json={"disclosure_consent_id": consent(s, "contact_disclosure")},
            headers=headers(s.auth, "accept-revised-app", new["version"]),
        ).status_code
        == 200
    )
    assert app_action(s, application, "status", body={"status": "hired"}).status_code == 409
    event = next(
        event
        for event in events(s, "invitation_accepted")
        if str(event.payload["invitation_id"]) == new["invitation_id"]
    )
    with Session(s.privacy.app.state.engine) as session, session.begin():
        assert process_accepted_invitation(session, event)
    assert app_action(s, application, "status", body={"status": "hired"}).status_code == 200


def test_hired_application_offer_revision_rolls_back(published):
    s = published
    application, invitation, app_path = prepare_offer(s)
    assert app_action(s, application, "status", body={"status": "hired"}).status_code == 200
    path = "/v1/invitations/" + invitation["invitation_id"]
    response = s.hiring.client.post(
        path + "/revisions",
        json=terms(s, "Cannot revise completed hiring"),
        headers=headers(s.employer_auth, "hired-no-revision", invitation["version"]),
    )
    assert response.status_code == 409, response.text
    assert s.hiring.client.get(path, headers=s.employer_auth).json() == invitation
    assert s.hiring.client.get(app_path, headers=s.employer_auth).json()["status"] == "hired"
