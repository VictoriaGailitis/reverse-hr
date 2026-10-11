"""Screening and durable review scheduling through signed migrated services."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.coordination.review_sla import run_one
from reverse_hr.services.hiring.domain.hiring_communication_risk import CommunicationRisk, signals
from reverse_hr.services.hiring.domain.hiring_dialogs import Complaint
from reverse_hr.services.hiring.domain.hiring_moderation import ComplaintCase
from reverse_hr.services.hiring.review_models import HiringAction, HiringSLA
from reverse_hr.shared.db import Outbox
from tests.integration.test_matching_hiring import setup as market_setup
from tests.services.hiring.test_hiring_dialogs import deliver_grant, send
from tests.services.hiring.test_hiring_dialogs import flow as dialog_flow
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

signatures = signatures_fixture
setup = market_setup
flow = dialog_flow


def test_screening_is_explainable_bounded_and_not_a_fraud_verdict():
    salary = {"salary": {"currency": "RUB", "minimum": 100000, "maximum": 150000}}
    assert signals("HTTPS://example.com/jobs No deposit needed", salary) == []
    assert signals("Не переводите деньги. Do not send money", salary) == []
    assert signals("Переведите депозит через https://bit.ly/secret", salary) == [
        "payment_request",
        "suspicious_link",
    ]
    assert signals("salary: 50000 RUB", salary) == ["salary_terms_mismatch"]
    assert signals("salary: 50000 RUB", salary, employer_message=False) == []
    assert signals("What if salary: 100000 RUB?", salary) == []
    assert signals("https://127.0.0.1/account", salary) == ["suspicious_link"]
    usd = {"salary": {"currency": "USD", "minimum": 1000, "maximum": 2000}}
    assert signals("salary: 500 USD", usd) == ["salary_terms_mismatch"]
    assert signals("salary: 500 EUR", usd) == []
    assert signals("salary: 500 RUB", usd) == []


def request(s):
    return SimpleNamespace(app=s.hiring.app, state=SimpleNamespace(trace_id=uuid4()))


def case(s):
    s.hiring.client._transport.raise_server_exceptions = True
    deliver_grant(s)
    result = send(s, text="Переведите депозит через https://bit.ly/private")
    assert result.status_code == 201, result.text
    with Session(s.hiring.app.state.engine) as session:
        risk = session.get(CommunicationRisk, result.json()["message_id"])
        return risk.complaint_id, risk.message_id


def test_risk_creation_replay_review_and_private_evidence(flow):
    s = flow
    complaint_id, message_id = case(s)
    assert send(s, text="Переведите депозит через https://bit.ly/private").status_code == 201
    with Session(s.hiring.app.state.engine) as session:
        assert len(list(session.scalars(select(CommunicationRisk)))) == 1
        risk = session.get(CommunicationRisk, message_id)
        assert "private" not in str(risk.data)
        row = session.get(ComplaintCase, complaint_id)
        assert row.status == "open"
        events = list(session.scalars(select(Outbox)))
        assert not any("bit.ly" in str(e.envelope) for e in events)
    path = f"/v1/hiring-complaints/{complaint_id}"
    assert s.hiring.client.get(path + "/risk-signal", headers=s.auth).status_code == 403
    evidence = s.hiring.client.get(path + "/risk-signal", headers=s.moderator)
    assert evidence.status_code == 200, evidence.text
    assert evidence.json()["message_id"] == message_id
    decided = s.hiring.client.post(
        path + "/decisions",
        json={"outcome": "dismissed", "reason": "Benign context reviewed"},
        headers=headers(s.moderator, "dismiss", 1),
    )
    assert decided.status_code == 200, decided.text
    assert (
        s.hiring.client.get(s.path + "/risk-signals", headers=s.auth).json()[0]["status"]
        == "dismissed"
    )


def test_sla_reminder_rotation_escalation_idempotency_terminal(flow):
    s = flow
    complaint_id, _ = case(s)
    now = datetime.now(UTC)
    # Heartbeat proves actual role+MFA; queue assignment never accepts arbitrary IDs.
    first = s.hiring.client.put("/v1/review-sla/availability", headers=s.moderator)
    assert first.status_code == 200, first.text
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.get(Complaint, complaint_id).created_at = now - timedelta(days=13, hours=1)
    assert run_one(request(s), now=now)
    assert not run_one(request(s), now=now)
    with Session(s.hiring.app.state.engine) as session:
        assert session.get(ComplaintCase, complaint_id).version == 1
        assert len(list(session.scalars(select(HiringAction)))) == 1
    # Refresh the lease at simulated times without waiting 24 hours.
    from reverse_hr.services.hiring.review_models import HiringReviewer

    with Session(s.hiring.app.state.engine) as session, session.begin():
        for row in session.scalars(select(HiringReviewer)):
            row.available_until = now + timedelta(days=4)
    assert run_one(request(s), now=now + timedelta(days=1))
    assert not run_one(request(s), now=now + timedelta(days=1))
    inbox = s.hiring.client.get("/v1/review-sla/inbox", headers=s.moderator)
    assert inbox.status_code == 200, inbox.text
    assert {a["event"] for a in inbox.json()} == {"reminder", "overdue", "reassigned"}
    with Session(s.hiring.app.state.engine) as session:
        ledger = session.get(HiringSLA, (complaint_id, "complaint"))
        first_id = ledger.data["reviewer_id"]
        assert ledger.version == 2
    second_id = uuid4()
    second = s.token(second_id, ("company_moderator",), amr=["mfa"])
    assert s.hiring.client.put("/v1/review-sla/availability", headers=second).status_code == 200
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.get(HiringReviewer, str(second_id)).available_until = now + timedelta(days=4)
    assert run_one(request(s), now=now + timedelta(days=3))
    assert not run_one(request(s), now=now + timedelta(days=3))
    with Session(s.hiring.app.state.engine) as session:
        ledger = session.get(HiringSLA, (complaint_id, "complaint"))
        assert ledger.data["reviewer_id"] == str(second_id)
        assert ledger.data["previous_reviewers"] == [first_id]
        assert ledger.version == 3
    path = f"/v1/hiring-complaints/{complaint_id}/decisions"
    payload = {"outcome": "dismissed", "reason": "Independent review"}
    assert (
        s.hiring.client.post(
            path, json=payload, headers=headers(s.moderator, "old-assignment", 3)
        ).status_code
        == 403
    )
    done = s.hiring.client.post(path, json=payload, headers=headers(second, "resolve-sla", 3))
    assert done.status_code == 200, done.text
    assert not run_one(request(s), now=now + timedelta(days=30))


def test_sla_privacy_and_no_pool_escalation(flow):
    from reverse_hr.services.hiring.domain.hiring import process_deletion_request
    from tests.services.code_runner.test_code_runner import deletion

    s = flow
    complaint_id, _ = case(s)
    now = datetime.now(UTC)
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.get(Complaint, complaint_id).created_at = now - timedelta(days=17)
    assert run_one(request(s), now=now)
    with Session(s.hiring.app.state.engine) as session:
        ledger = session.get(HiringSLA, (complaint_id, "complaint"))
        assert ledger.data["reviewer_id"] is None
        assert ledger.data["stage"] == "escalated"
    assert not run_one(request(s), now=now)
    assert (
        s.hiring.client.put("/v1/review-sla/availability", headers=s.moderator).status_code == 200
    )
    assert run_one(request(s), now=now)
    assert not run_one(request(s), now=now)
    with Session(s.hiring.app.state.engine) as session:
        ledger = session.get(HiringSLA, (complaint_id, "complaint"))
        assert ledger.data["reviewer_id"] is not None
        assert ledger.data["stage"] == "escalated"
    with Session(s.hiring.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(UUID(str(s.candidate_id))))
    with Session(s.hiring.app.state.engine) as session:
        assert list(session.scalars(select(CommunicationRisk))) == []
        assert list(session.scalars(select(HiringSLA))) == []
        assert list(session.scalars(select(HiringAction))) == []
    assert not run_one(request(s), now=now)


def test_restricted_reviewer_recovery_uses_fresh_independent_permission(flow, monkeypatch):
    from fastapi import HTTPException

    s = flow
    complaint_id, _ = case(s)
    now = datetime.now(UTC)
    assert (
        s.hiring.client.put("/v1/review-sla/availability", headers=s.moderator).status_code == 200
    )
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.get(Complaint, complaint_id).created_at = now - timedelta(days=17)
    assert run_one(request(s), now=now)
    with Session(s.hiring.app.state.engine) as session:
        old = session.get(HiringSLA, (complaint_id, "complaint")).data["reviewer_id"]
    peer_id = uuid4()
    peer = s.token(peer_id, ("company_moderator",), amr=["mfa"])
    assert s.hiring.client.put("/v1/review-sla/availability", headers=peer).status_code == 200
    original = s.hiring.app.state.processing_access.check

    def permission(subject):
        if str(subject) == old:
            raise HTTPException(403)
        return original(subject)

    monkeypatch.setattr(s.hiring.app.state.processing_access, "check", permission)
    assert run_one(request(s), now=now)
    assert not run_one(request(s), now=now)
    with Session(s.hiring.app.state.engine) as session:
        ledger = session.get(HiringSLA, (complaint_id, "complaint"))
        assert ledger.data["reviewer_id"] == str(peer_id)
        assert old in ledger.data["previous_reviewers"]


def test_parallel_workers_emit_one_durable_escalation(flow):
    from concurrent.futures import ThreadPoolExecutor

    s = flow
    complaint_id, _ = case(s)
    now = datetime.now(UTC)
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.get(Complaint, complaint_id).created_at = now - timedelta(days=17)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: run_one(request(s), now=now), range(2)))
    assert sorted(results) == [False, True]
    with Session(s.hiring.app.state.engine) as session:
        actions = list(session.scalars(select(HiringAction)))
        assert sorted(x.data["event"] for x in actions) == ["escalated", "unassigned"]
        assert session.get(ComplaintCase, complaint_id).version == 2


def test_inbox_cursor_advances_past_hidden_page_without_exposing_cases(flow):
    s = flow
    complaint_id, _ = case(s)
    now = datetime.now(UTC)
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.get(Complaint, complaint_id).created_at = now - timedelta(days=17)
        for index in range(1, 51):
            session.add(
                HiringAction(
                    action_id=str(UUID(int=index)),
                    case_id=str(uuid4()),
                    kind="complaint",
                    recipient_id=str(uuid4()),
                    version=2,
                    at=now,
                    data={
                        "event": "escalated",
                        "due_at": now.isoformat(),
                        "rule_version": "review-sla-v1",
                    },
                )
            )
    assert run_one(request(s), now=now)
    first = s.hiring.client.get("/v1/review-sla/inbox", headers=s.moderator)
    assert first.status_code == 200, first.text
    assert first.json() == []
    assert first.headers["X-HR-Next-Cursor"] == str(UUID(int=50))
    second = s.hiring.client.get(
        "/v1/review-sla/inbox",
        params={"after": first.headers["X-HR-Next-Cursor"]},
        headers=s.moderator,
    )
    assert second.status_code == 200, second.text
    assert len(second.json()) == 2
    assert {item["case_id"] for item in second.json()} == {complaint_id}
    assert "X-HR-Next-Cursor" not in second.headers
