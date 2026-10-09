"""Employment conditions are explicit self-descriptions with fresh consent gates."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy.orm import Session
from test_access import headers
from test_event_transport import signatures as signatures_fixture
from test_matching_governance import approve_policy, create_versions, search
from test_matching_hiring import publication
from test_matching_hiring import setup as matching_fixture
from test_matching_qualification import evidence, inject, refresh

from reverse_hr.domains.candidate_preferences import PreferenceRow, apply_preferences_correction
from reverse_hr.domains.matching_governance import ParsedIntent, Vocabulary, validate_intent
from reverse_hr.matching_conditions import (
    CandidatePreferenceCommand,
    CandidatePreferences,
    EmploymentConditions,
    MonthlySalary,
    StartWindow,
    compare_conditions,
)

signatures = signatures_fixture
setup = matching_fixture


def salary(minimum=100000, maximum=200000, tax_basis="gross"):
    return {
        "currency": "RUB",
        "period": "month",
        "tax_basis": tax_basis,
        "minimum": minimum,
        "maximum": maximum,
    }


def conditions():
    today = datetime.now(UTC).date()
    return {
        "salary": salary(),
        "work_formats": ["remote"],
        "start_window": {
            "earliest": (today + timedelta(days=2)).isoformat(),
            "latest": (today + timedelta(days=20)).isoformat(),
        },
    }


def set_need_conditions(s, terms):
    body = {
        k: s.need[k]
        for k in (
            "organization_id",
            "specialization",
            "confirmed_grade",
            "required_skills",
            "status",
        )
    }
    body["conditions"] = terms
    response = s.hiring.client.put(
        f"/v1/hiring-needs/{s.need['need_id']}",
        json=body,
        headers=headers(s.employer_auth, str(uuid4()), s.need["version"]),
    )
    assert response.status_code == 200, response.text
    s.need = response.json()


def put_preferences(s, *, version=0, shared=True, terms=None, key=None, tolerance=0):
    return s.candidate.client.put(
        "/v1/candidates/me/preferences",
        json={
            **(terms or conditions()),
            "salary_tolerance_percent": tolerance,
            "share_in_matching": shared,
            "confirmed": True,
        },
        headers={**headers(s.auth, key or str(uuid4())), "If-Match": f'"{version}"'},
    )


def test_confirmed_public_preferences_actual_governed_filters_and_withdrawal(setup):
    s = setup
    create_versions(s)
    approve_policy(s)
    inject(s, evidence())
    set_need_conditions(s, conditions())
    assert search(s).json()["matches"] == []
    own = put_preferences(s, shared=False)
    assert own.status_code == 200, own.text
    assert own.json()["provenance"] == "candidate_confirmed_self_description"
    refresh(s)
    assert search(s).json()["matches"] == []
    shared = put_preferences(s, version=1)
    assert shared.status_code == 200, shared.text
    refresh(s)
    matched = search(s)
    assert matched.status_code == 201, matched.text
    card = matched.json()["matches"][0]
    assert card["preferences"]["version"] == 2
    assert card["condition_comparison"]["eligible"] is True
    assert card["condition_comparison"]["salary"] == "compatible"
    assert "self-description" in card["explanation"]
    assert "email" not in card and "phone" not in card
    assert put_preferences(s, version=1).status_code == 409
    withdrawn = put_preferences(s, version=2, shared=False)
    assert withdrawn.status_code == 200
    refresh(s)
    path = f"/v1/matches/{matched.json()['snapshot_id']}"
    assert s.matching.client.get(path, headers=headers(s.employer_auth)).json()["matches"] == []
    assert search(s).json()["matches"] == []
    own = s.candidate.client.get("/v1/candidates/me/preferences", headers=headers(s.auth)).json()
    assert own["preferences"]["salary"]["minimum"] == 100000
    assert own["share_in_matching"] is False


def test_preferences_missing_values_are_not_unbounded_or_exchange_converted():
    company = EmploymentConditions.model_validate(conditions())
    candidate = CandidatePreferences(**conditions(), version=1, confirmed_at=datetime.now(UTC))
    assert compare_conditions(company, candidate).eligible
    assert not compare_conditions(company, None).eligible
    missing = candidate.model_copy(
        update={"salary": None, "work_formats": [], "start_window": None}
    )
    result = compare_conditions(company, missing)
    assert result.salary == result.work_format == result.availability == "unknown"
    net = candidate.model_copy(
        update={"salary": MonthlySalary.model_validate(salary(tax_basis="net"))}
    )
    assert compare_conditions(company, net).salary == "unknown"
    wrong_format = candidate.model_copy(update={"work_formats": ["onsite"]})
    assert compare_conditions(company, wrong_format).work_format == "incompatible"
    old = candidate.model_copy(update={"confirmed_at": datetime.now(UTC) - timedelta(days=91)})
    assert not compare_conditions(company, old).eligible
    with pytest.raises(ValidationError):
        MonthlySalary.model_validate({**salary(), "currency": "USD"})
    with pytest.raises(ValidationError):
        CandidatePreferenceCommand(confirmed=True, salary_tolerance_percent=10)
    with pytest.raises(ValidationError):
        CandidatePreferenceCommand(confirmed=1)


def test_salary_touching_ranges_and_explicit_tolerance_date_boundaries():
    now = datetime.now(UTC)
    company = EmploymentConditions(salary=MonthlySalary.model_validate(salary(100000, 150000)))
    candidate = CandidatePreferences(
        salary=MonthlySalary.model_validate(salary(150000, 200000)), version=1, confirmed_at=now
    )
    assert compare_conditions(company, candidate).salary == "compatible"
    candidate.salary = MonthlySalary.model_validate(salary(150001, 200000))
    assert compare_conditions(company, candidate).salary == "incompatible"
    candidate.salary_tolerance_percent = 1
    assert compare_conditions(company, candidate).salary == "compatible"
    window = StartWindow(earliest=now.date(), latest=now.date())
    company.start_window = window
    candidate.start_window = window
    assert compare_conditions(company, candidate, now=now).availability == "compatible"
    assert (
        compare_conditions(company, candidate, now=now + timedelta(days=1)).availability
        == "incompatible"
    )
    with pytest.raises(ValidationError):
        StartWindow(earliest="2026-10-10T00:00:00Z", latest="2026-10-12")


def test_own_preferences_replay_returns_current_values_and_correction_cas(setup):
    s = setup
    first = put_preferences(s, key="initial-prefs")
    assert first.status_code == 200
    changed = put_preferences(
        s, version=1, terms={**conditions(), "salary": salary(180000, 220000)}
    )
    assert changed.status_code == 200
    replay = put_preferences(s, key="initial-prefs")
    assert replay.status_code == 200
    assert replay.json()["salary"]["minimum"] == 180000
    from reverse_hr.domains.candidate import CandidateProfile

    with Session(s.candidate.app.state.engine) as session, session.begin():
        profile = session.get(CandidateProfile, str(s.candidate_id))
        current = profile.version
        with pytest.raises(HTTPException):
            apply_preferences_correction(
                session,
                s.candidate_id,
                {**conditions(), "confirmed": True},
                2,
                uuid4(),
                expected_profile_version=current - 1,
            )
        corrected = apply_preferences_correction(
            session,
            s.candidate_id,
            {**conditions(), "confirmed": True, "share_in_matching": False},
            2,
            uuid4(),
            expected_profile_version=current,
        )
        assert corrected["version"] == 3 and corrected["share_in_matching"] is False
        assert profile.version == current + 1


def test_profile_publication_consent_and_fresh_after_build_checks(setup):
    s = setup
    put_preferences(s)
    set_need_conditions(s, conditions())
    assert publication(s, False).status_code == 200
    refresh(s)
    create_versions(s)
    approve_policy(s)
    assert search(s).json()["matches"] == []
    assert publication(s, True).status_code == 200
    refresh(s)
    inject(s, evidence())
    original = s.candidate.app.state.market_access.require
    calls = 0

    def permitted(*args, **kwargs):
        nonlocal calls
        if args[:2] == ("privacy", "purpose-permission"):
            calls += 1
            if calls == 2:
                raise HTTPException(409)
        return original(*args, **kwargs)

    s.candidate.app.state.market_access.require = permitted
    receipt = s.matching.app.state.market_access.fetch(
        "candidate", "profile", candidate_id=s.candidate_id
    )
    assert receipt.allowed is False
    assert receipt.data is None


def test_matching_drops_expired_preference_without_overwriting_confirmation(setup):
    s = setup
    create_versions(s)
    approve_policy(s)
    inject(s, evidence())
    put_preferences(s)
    refresh(s)
    set_need_conditions(s, conditions())
    assert len(search(s).json()["matches"]) == 1
    with Session(s.candidate.app.state.engine) as session, session.begin():
        row = session.get(PreferenceRow, str(s.candidate_id))
        row.confirmed_at = datetime.now(UTC) - timedelta(days=91)
    assert search(s).json()["matches"] == []


def test_semantic_typed_conditions_source_quotes_unknowns_and_no_imaginary_numbers():
    catalog = Vocabulary(
        version="v1",
        specializations=["backend"],
        entries=[{"key": "python", "evidence_keys": ["python"]}],
    )
    text = "100-200 тыс рублей в месяц gross, remote. Выход с 2026-11-01 до 2026-11-20."
    intent = ParsedIntent(
        employment_conditions=EmploymentConditions(
            salary=MonthlySalary.model_validate(salary()),
            work_formats=["remote"],
            start_window=StartWindow(earliest="2026-11-01", latest="2026-11-20"),
        ),
        citations={
            "salary.minimum": "100-200 тыс",
            "salary.maximum": "100-200 тыс",
            "salary.currency": "рублей",
            "salary.period": "месяц",
            "salary.tax_basis": "gross",
            "work_format:remote": "remote",
            "start_window.earliest": "2026-11-01",
            "start_window.latest": "2026-11-20",
        },
    )
    # The first endpoint without its own multiplier is deliberately not invented from a range.
    with pytest.raises(HTTPException):
        validate_intent(intent, catalog, text)
    text = text.replace("100-200 тыс", "100 тыс - 200 тыс")
    intent.citations["salary.minimum"] = "100 тыс"
    intent.citations["salary.maximum"] = "200 тыс"
    assert validate_intent(intent, catalog, text).employment_conditions.salary.minimum == 100000
    missing = validate_intent(ParsedIntent(), catalog, text)
    assert {"salary", "work_format", "availability"} <= set(missing.unknowns)
    invented = intent.model_copy(deep=True)
    invented.employment_conditions.salary.minimum = 125000
    with pytest.raises(HTTPException):
        validate_intent(invented, catalog, text)


def test_typed_semantic_confirmation_search_and_invitation_keep_company_terms(setup):
    s = setup
    create_versions(s)
    approve_policy(s)
    inject(s, evidence())
    terms = conditions()
    set_need_conditions(s, terms)
    assert put_preferences(s).status_code == 200
    refresh(s)
    dates = terms["start_window"]
    text = (
        f"backend middle python. salary 100000-200000 RUB/month gross remote "
        f"start date {dates['earliest']} - {dates['latest']}"
    )
    proposal = ParsedIntent(
        specialization="backend",
        grade="middle",
        mandatory=["python"],
        employment_conditions=EmploymentConditions.model_validate(terms),
        citations={
            "specialization": "backend",
            "grade": "middle",
            "mandatory:python": "python",
            "salary.minimum": "100000",
            "salary.maximum": "200000",
            "salary.currency": "RUB",
            "salary.period": "month",
            "salary.tax_basis": "gross",
            "work_format:remote": "remote",
            "start_window.earliest": dates["earliest"],
            "start_window.latest": dates["latest"],
        },
    )
    s.matching.app.state.matching_intent_gateway = SimpleNamespace(
        parse=lambda inputs, **kwargs: proposal
    )
    parsed = s.matching.client.post(
        "/v1/matches/intent-previews",
        json={
            "organization_id": s.organization_id,
            "need_id": s.need["need_id"],
            "catalog_id": s.catalog,
            "text": text,
            "parser": "llm",
        },
        headers=headers(s.employer_auth, "typed-preview"),
    )
    assert parsed.status_code == 201, parsed.text
    parsed = parsed.json()
    confirmed = s.matching.client.post(
        f"/v1/matches/intent-previews/{parsed['preview_id']}/confirmation",
        json=parsed["proposal"],
        headers=headers(s.employer_auth, "typed-confirm"),
    )
    assert confirmed.status_code == 200, confirmed.text
    selected = search(s, parsed["preview_id"])
    assert selected.status_code == 201, selected.text
    assert len(selected.json()["matches"]) == 1
    invitation = s.hiring.client.post(
        "/v1/invitations",
        json={
            "organization_id": s.organization_id,
            "candidate_id": str(s.candidate_id),
            "description": "Backend role",
            "employer_contact": "recruiter@example.test",
            "salary": terms["salary"],
            "conditions": terms,
        },
        headers=headers(s.employer_auth, "typed-invite"),
    )
    assert invitation.status_code == 201, invitation.text
    assert invitation.json()["conditions"] == terms
    from test_matching_hiring import consent

    accepted = s.hiring.client.post(
        f"/v1/invitations/{invitation.json()['invitation_id']}/accept",
        json={"disclosure_consent_id": consent(s, "contact_disclosure")},
        headers=headers(s.auth, "typed-accept", 1),
    )
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["conditions"] == terms
    invalid = proposal.model_copy(deep=True)
    invalid.employment_conditions.salary.maximum = 250000
    # Employer confirmation must not privately change an existing company offer.
    assert (
        s.matching.client.post(
            f"/v1/matches/intent-previews/{parsed['preview_id']}/confirmation",
            json=invalid.model_dump(mode="json"),
            headers=headers(s.employer_auth, "alter-offer"),
        ).status_code
        == 409
    )


def test_privacy_deletion_erases_preferences_and_blocks_late_replay(setup):
    from test_code_runner import deletion

    from reverse_hr.domains.candidate import process_deletion_request

    s = setup
    assert put_preferences(s, key="before-deletion").status_code == 200
    with Session(s.candidate.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate_id))
    with Session(s.candidate.app.state.engine) as session:
        assert session.get(PreferenceRow, str(s.candidate_id)) is None
    assert put_preferences(s, key="before-deletion").status_code == 409
    receipt = s.matching.app.state.market_access.fetch(
        "candidate", "profile", candidate_id=s.candidate_id
    )
    assert receipt.allowed is False and receipt.data is None


def test_immutable_old_policy_digest_remains_valid_after_optional_preference_limit_added(setup):
    from reverse_hr.domains.matching_governance import GovernanceVersion, document_digest

    s = setup
    create_versions(s)
    approve_policy(s)
    with Session(s.matching.app.state.engine) as session, session.begin():
        row = session.get(GovernanceVersion, s.policy)
        old = {k: v for k, v in row.document.items() if k != "maximum_preference_age_days"}
        row.document = old
        row.content_digest = document_digest(old)
    assert search(s).status_code == 201
