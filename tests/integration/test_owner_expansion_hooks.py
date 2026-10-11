"""Cross-owner condition propagation and disclosure receipts at real HTTP boundaries."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.services.hiring.domain.hiring import Need
from reverse_hr.shared.db import Outbox
from tests.integration.test_matching_hiring import setup as market_setup
from tests.services.hiring.test_hiring_vacancies import app_action, apply, create, vacancy_action
from tests.shared.test_event_transport import signatures as signatures_fixture

setup = market_setup
signatures = signatures_fixture


def test_vacancy_conditions_reach_signed_need_and_application_invitation(setup):
    s = setup
    terms = {"work_formats": ["remote"], "start_window": None}
    reply = create(s, conditions=terms)
    assert reply.status_code == 201, reply.text
    row = reply.json()
    assert row["conditions"]["salary"] == row["salary"]
    assert row["requirements"]["conditions"] == row["conditions"]
    with Session(s.hiring.app.state.engine) as session:
        need = session.get(Need, row["need_id"])
        assert need.spec["conditions"] == row["conditions"]
    row = vacancy_action(s, row, "submit").json()
    row = vacancy_action(
        s,
        row,
        "review",
        auth=s.moderator,
        body={"outcome": "approved", "reason": "Independent synthetic review"},
    ).json()
    row = vacancy_action(s, row, "publish").json()
    s.vacancy, s.vpath = row, "/v1/vacancies/" + row["vacancy_id"]
    application = apply(s)
    assert application.status_code == 201, application.text
    invited = app_action(s, application.json(), "invite", body={})
    assert invited.status_code == 200, invited.text
    invitation = s.hiring.client.get(
        "/v1/invitations/" + invited.json()["invitation_id"],
        headers=s.auth,
    ).json()
    assert invitation["conditions"] == row["conditions"]


def test_conflicting_salary_is_rejected_before_persisting_vacancy(setup):
    s = setup
    reply = create(
        s,
        conditions={
            "salary": {
                "tax_basis": "gross",
                "minimum": 1,
                "maximum": 2,
            }
        },
    )
    assert reply.status_code == 422
    with Session(s.hiring.app.state.engine) as session:
        assert session.scalar(select(Need)) is not None  # Existing fixture need remains.
        assert not any(
            "disclosed" in item.envelope["event_type"] for item in session.scalars(select(Outbox))
        )
