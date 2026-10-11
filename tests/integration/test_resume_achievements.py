"""Signed achievement export and actual bounded PDF guest text/render output."""

from pathlib import Path
from uuid import uuid4

from tests.integration.test_achievements_integration import connect, publish, rows, synchronize
from tests.integration.test_achievements_integration import setup as setup
from tests.integration.test_achievements_integration import signatures as signatures
from tests.services.candidate.test_candidate_resumes import FIELDS, download, text
from tests.services.candidate.test_candidate_resumes import guest as guest
from tests.shared.test_access import headers


def resume(s, guest):
    s.candidate.app.state.settings.resume_achievements_enabled = True
    s.candidate.app.state.resume_guest = guest
    profile = s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()
    saved = s.candidate.client.put(
        "/v1/candidates/me/resume",
        json=FIELDS | {"profile_version": profile["version"]},
        headers=headers(s.auth, "save-ach-resume", 1),
    )
    assert saved.status_code == 200, saved.text
    synchronize(s, connect(s))
    return publish(s, rows(s)[0])


def test_pdf_confirmed_achievements_text_and_withdrawal(setup, guest):
    s = setup
    item = resume(s, guest)
    full = download(s, variant="full", own=True)
    full_text = text(full)
    assert "Verified achievements" in full_text and "DEMO ACHIEVEMENT" in full_text
    assert item["result"]["event"] in full_text
    assert "Checked:" in full_text and "Source:" in full_text
    assert "anna@example.test" in full_text
    anonymous = download(s, own=True)
    anonymous_text = text(anonymous)
    assert "Verified achievements" in anonymous_text and "anna@example.test" not in anonymous_text
    assert "Анна Иванова" not in anonymous_text
    Path("/private/tmp/resume-achievements-full.pdf").write_bytes(full.content)
    Path("/private/tmp/resume-achievements-anonymous.pdf").write_bytes(anonymous.content)
    hidden = s.achievements.client.put(
        "/v1/achievements/" + item["achievement_id"] + "/visibility",
        json={"published": False},
        headers=headers(s.auth, "hide-ach", item["version"]),
    )
    assert hidden.status_code == 200, hidden.text
    assert "Verified achievements" not in text(download(s, own=True))


def test_pdf_changed_evidence_during_render_rejected(setup, guest):
    s = setup
    item = resume(s, guest)

    class RacingGuest:
        def render(self, data):
            result = guest.render(data)
            response = s.achievements.client.put(
                "/v1/achievements/" + item["achievement_id"] + "/visibility",
                json={"published": False},
                headers=headers(s.auth, str(uuid4()), item["version"]),
            )
            assert response.status_code == 200
            return result

    s.candidate.app.state.resume_guest = RacingGuest()
    assert download(s, own=True).status_code == 409


def test_production_pdf_excludes_demo_achievements(setup, guest):
    s = setup
    resume(s, guest)
    s.candidate.app.state.settings.deployment_mode = "production"
    assert "DEMO ACHIEVEMENT" not in text(download(s, own=True))


def test_source_disable_during_render_rejects_pdf(setup, guest):
    from sqlalchemy.orm import Session

    from reverse_hr.services.achievements.domain.achievements import SourceRow

    s = setup
    item = resume(s, guest)

    class SourceRace:
        def render(self, data):
            output = guest.render(data)
            with Session(s.achievements.app.state.engine) as session, session.begin():
                row = session.get(SourceRow, item["source_id"])
                row.enabled, row.version = False, row.version + 1
            return output

    s.candidate.app.state.resume_guest = SourceRace()
    assert download(s, own=True).status_code == 409


def test_replacement_closes_existing_ats_read_permission(setup):
    from reverse_hr.services.integration.domain.integration import run_one
    from tests.integration.test_achievements_integration import export_setup, request_for
    from tests.services.hiring.test_invitation_lifecycle import terms

    s = setup
    body, queued = export_setup(s)
    invitation_id = body["invitation_id"]
    assert run_one(request_for(s.integration))
    job = s.integration.client.get(
        "/v1/integrations/jobs/" + queued["job_id"], headers=s.employer_auth
    ).json()
    path = "/v1/ats/candidates/" + job["external_id"]
    assert s.demo_ats.client.get(path, headers=s.employer_auth).status_code == 200
    changed = s.hiring.client.post(
        "/v1/invitations/" + invitation_id + "/revisions",
        json=terms(s, "Updated accepted terms"),
        headers=headers(s.employer_auth, "ats-revise", 2),
    )
    assert changed.status_code == 201, changed.text
    assert s.demo_ats.client.get(path, headers=s.employer_auth).status_code in {403, 409}
