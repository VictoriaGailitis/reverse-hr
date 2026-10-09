"""Approved owner CAS commands edit only candidate-owned declarations."""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session
from test_access import headers
from test_achievements_integration import signatures as signatures  # noqa: F401
from test_privacy_subject_requests import approve, submit  # noqa: F401
from test_privacy_subject_requests import setup as setup

from reverse_hr.domains.candidate import CandidateProfile
from reverse_hr.domains.candidate_market import Contacts
from reverse_hr.domains.candidate_resume import Resume


def execute(s, row):
    path = "/v1/data-subject-requests/" + row["request_id"] + "/execute"
    key = str(uuid4())
    response = s.privacy.client.post(path, headers=headers(s.officer, key, row["version"]))
    assert response.status_code == 200, response.text
    repeated = s.privacy.client.post(path, headers=headers(s.officer, key, row["version"]))
    assert repeated.json() == response.json()
    return response.json()


@pytest.mark.parametrize("target", ["contacts", "resume", "preferences"])
def test_versioned_candidate_corrections_and_owner_receipt(setup, target):
    s = setup
    with Session(s.candidate.app.state.engine) as session, session.begin():
        profile = session.get(CandidateProfile, str(s.candidate_id))
        profile_version = profile.version
        fields = dict(
            display_name=profile.display_name,
            specialization=profile.specialization,
            declared_grade=profile.declared_grade,
            declared_skills=[],
            summary="Before",
            experience=[],
            education=[],
            contacts=None,
        )
        if target == "contacts":
            session.add(
                Contacts(
                    candidate_id=str(s.candidate_id),
                    email="old@example.test",
                    phone=None,
                    version=1,
                )
            )
            changes = dict(email="corrected@example.test", phone=None)
            expected = 1
        elif target == "resume":
            session.add(
                Resume(
                    candidate_id=str(s.candidate_id),
                    fields=fields,
                    version=1,
                    published=False,
                    consent_id=None,
                )
            )
            changes = fields | {"summary": "Corrected candidate self-description"}
            expected = 1
        else:
            changes = dict(
                confirmed=True,
                work_formats=["remote"],
                salary=None,
                start_window=None,
                salary_tolerance_percent=0,
                share_in_matching=False,
            )
            expected = 0
    row = approve(
        s,
        submit(
            s,
            kind="correction",
            domain="candidate",
            target=target,
            source_version=expected,
            source_profile_version=profile_version,
            proposed_changes=changes,
        ),
    )
    result = execute(s, row)
    assert result["status"] == "completed"
    assert result["data"]["result"]["target"] == target
    assert result["data"]["result"]["version"] == expected + 1
    with Session(s.candidate.app.state.engine) as session:
        if target == "contacts":
            assert session.get(Contacts, str(s.candidate_id)).email == "corrected@example.test"
        elif target == "resume":
            assert session.get(Resume, str(s.candidate_id)).fields["summary"] == changes["summary"]
        else:
            from reverse_hr.domains.candidate_preferences import PreferenceRow

            assert session.get(PreferenceRow, str(s.candidate_id)).document["work_formats"] == [
                "remote"
            ]


def test_contact_source_conflict_does_not_overwrite_new_data(setup):
    s = setup
    with Session(s.candidate.app.state.engine) as session, session.begin():
        session.add(
            Contacts(
                candidate_id=str(s.candidate_id),
                email="current@example.test",
                phone=None,
                version=2,
            )
        )
    row = approve(
        s,
        submit(
            s,
            kind="correction",
            domain="candidate",
            target="contacts",
            source_version=1,
            proposed_changes={"email": "stale@example.test", "phone": None},
        ),
    )
    response = s.privacy.client.post(
        "/v1/data-subject-requests/" + row["request_id"] + "/execute",
        headers=headers(s.officer, str(uuid4()), row["version"]),
    )
    assert response.status_code == 409
    with Session(s.candidate.app.state.engine) as session:
        assert session.get(Contacts, str(s.candidate_id)).email == "current@example.test"


def test_verified_achievement_immutable_under_correction(setup):
    from test_achievements_integration import connect, rows, synchronize

    s = setup
    synchronize(s, connect(s))
    achievement = rows(s)[0]
    from reverse_hr.domains.achievements import AchievementRow

    with Session(s.achievements.app.state.engine) as session:
        before = dict(session.get(AchievementRow, achievement["achievement_id"]).data)
    fields = {
        k: before[k]
        for k in (
            "event",
            "discipline",
            "occurred_on",
            "specialization",
            "format",
            "place",
            "points",
            "group_size",
            "evidence_url",
        )
    }
    fields["event"] = "Attempt to rewrite imported evidence"
    row = approve(
        s,
        submit(
            s,
            kind="correction",
            domain="achievements",
            target="declared_achievement",
            target_id=achievement["achievement_id"],
            source_version=achievement["version"],
            proposed_changes=fields,
        ),
    )
    response = s.privacy.client.post(
        "/v1/data-subject-requests/" + row["request_id"] + "/execute",
        headers=headers(s.officer, str(uuid4()), row["version"]),
    )
    assert response.status_code == 409, response.text
    with Session(s.achievements.app.state.engine) as session:
        assert session.get(AchievementRow, achievement["achievement_id"]).data == before


def test_self_declared_achievement_corrected_without_confirming_evidence(setup):
    s = setup
    fields = dict(
        event="Self reported contest",
        discipline="Python",
        occurred_on="2026-01-01",
        specialization="backend",
        format="individual",
        place=1,
        points=10,
        group_size=2,
        evidence_url=None,
    )
    response = s.achievements.client.post(
        "/v1/achievements/declared",
        json=fields | {"consent_id": s.import_consent},
        headers=headers(s.auth, str(uuid4())),
    )
    assert response.status_code == 201, response.text
    achievement = response.json()
    row = approve(
        s,
        submit(
            s,
            kind="correction",
            domain="achievements",
            target="declared_achievement",
            target_id=achievement["achievement_id"],
            source_version=achievement["version"],
            proposed_changes=fields | {"event": "Corrected self reported contest"},
        ),
    )
    execute(s, row)
    from reverse_hr.domains.achievements import AchievementRow

    with Session(s.achievements.app.state.engine) as session:
        result = session.get(AchievementRow, achievement["achievement_id"])
        assert result.data["event"] == "Corrected self reported contest"
        assert result.status == "declared"
        assert result.published is False


def test_notification_preferences_owner_cas(setup, service, signatures):
    from reverse_hr.domains.notification import Preference
    from reverse_hr.privacy_request_exchange import RightsAccess

    s = setup
    target = service("notification")
    s.targets["notification"] = target
    access = RightsAccess(target.app.state.settings)
    access._signatures, access._send = signatures["notification"], s.sender
    target.app.state.rights_access = access
    with Session(target.app.state.engine) as session, session.begin():
        session.add(
            Preference(subject=str(s.candidate_id), in_app=True, marketing_in_app=False, version=1)
        )
    row = approve(
        s,
        submit(
            s,
            kind="correction",
            domain="notification",
            target="notification_preferences",
            source_version=1,
            proposed_changes={"in_app": False, "marketing_in_app": False},
        ),
    )
    execute(s, row)
    with Session(target.app.state.engine) as session:
        prefs = session.get(Preference, str(s.candidate_id))
        assert prefs.in_app is False and prefs.version == 2
