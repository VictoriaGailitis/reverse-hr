"""Independent complaint moderation with current access and erasure fences."""

from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture
from test_hiring_dialogs import deliver_grant, send
from test_hiring_dialogs import flow as dialog_flow
from test_matching_hiring import setup as market_setup

from reverse_hr.db import IdempotencyRecord, Outbox
from reverse_hr.domains.hiring import process_deletion_request
from reverse_hr.domains.hiring_dialogs import Complaint
from reverse_hr.domains.hiring_moderation import ComplaintCase, ComplaintDecision
from reverse_hr.migrate import migration_config

signatures = signatures_fixture
setup = market_setup
flow = dialog_flow


@pytest.fixture
def case(flow):
    s = flow
    deliver_grant(s)
    msg = send(s, auth=s.employer_auth).json()
    response = s.hiring.client.post(
        s.path + "/complaints",
        json={"reason": "Synthetic complaint", "message_id": msg["message_id"]},
        headers=headers(s.auth, "complaint"),
    )
    assert response.status_code == 201
    s.cid = response.json()["complaint_id"]
    s.casepath = "/v1/hiring-complaints/" + s.cid
    s.reviewer_id = uuid4()
    s.reviewer = s.token(s.reviewer_id, ("company_moderator",), amr=["mfa"])
    return s


def decide(s, key="decision", version=1, auth=None, outcome="upheld"):
    return s.hiring.client.post(
        s.casepath + "/decisions",
        json={"outcome": outcome, "reason": "Reviewed the reported message"},
        headers=headers(auth or s.reviewer, key, version),
    )


@pytest.mark.parametrize("outcome", ["upheld", "dismissed"])
def test_queue_bounded_evidence_independent_decision_and_own_status(case, outcome):
    s = case
    queue = s.hiring.client.get("/v1/hiring-complaints", headers=s.reviewer)
    assert queue.status_code == 200 and len(queue.json()) == 1
    assert "reason" not in queue.json()[0] and "message" not in queue.json()[0]
    evidence = s.hiring.client.get(s.casepath, headers=s.reviewer)
    assert evidence.status_code == 200
    assert evidence.json()["message"]["text"] == "Hello, can we discuss the role?"
    assert "employer_contact" not in evidence.text and "email" not in evidence.text
    result = decide(s, outcome=outcome)
    assert result.status_code == 200 and result.json()["status"] == outcome
    assert result.json()["version"] == 2 and len(result.json()["decisions"]) == 1
    assert decide(s, outcome=outcome).json() == result.json()
    assert decide(s, "another", 2).status_code == 409
    assert s.hiring.client.get("/v1/hiring-complaints", headers=s.reviewer).json() == []
    own = s.hiring.client.get(s.path + "/complaints/" + s.cid, headers=s.auth)
    assert own.status_code == 200 and own.json()["status"] == outcome
    assert "decisions" not in own.json() and "message" not in own.json()
    with Session(s.hiring.app.state.engine) as session:
        assert len(list(session.scalars(select(ComplaintDecision)))) == 1
        assert not any(
            "Reviewed the reported" in row.response
            for row in session.scalars(select(IdempotencyRecord))
        )
        outbox = [
            r
            for r in session.scalars(select(Outbox))
            if r.envelope["event_type"] == "hiring.complaint_decided.v1"
        ]
        assert len(outbox) == 1
        assert all(isinstance(v, str) for v in outbox[0].envelope["payload"].values())


@pytest.mark.parametrize("kind", ["no_mfa", "candidate", "author", "employee"])
def test_mfa_roles_and_conflict_of_interest(case, kind):
    s = case
    if kind == "no_mfa":
        auth = s.token(uuid4(), ("company_moderator",))
    elif kind == "candidate":
        auth = s.auth
    elif kind == "author":
        auth = s.token(s.candidate_id, ("candidate", "company_moderator"), amr=["mfa"])
    else:
        subject = uuid4()
        result = s.employer.client.post(
            f"/v1/organizations/{s.organization_id}/members",
            json={"subject": str(subject), "role": "technical_expert"},
            headers=headers(s.employer_auth, "staff", 2),
        )
        assert result.status_code == 201
        auth = s.token(subject, ("company_moderator",), amr=["mfa"])
    assert s.hiring.client.get(s.casepath, headers=auth).status_code == 403
    assert decide(s, auth=auth).status_code == 403
    if kind in {"author", "employee"}:
        assert s.hiring.client.get("/v1/hiring-complaints", headers=auth).json() == []


def test_moderation_stale_version_and_source_failure(case):
    s = case
    assert decide(s, version=2).status_code == 409

    def unavailable(*args, **kwargs):
        raise HTTPException(503)

    s.hiring.app.state.market_access._send = unavailable
    assert s.hiring.client.get(s.casepath, headers=s.reviewer).status_code == 503
    assert decide(s).status_code == 503
    with Session(s.hiring.app.state.engine) as session:
        assert session.get(ComplaintCase, s.cid).status == "open"
        assert session.scalar(select(ComplaintDecision)) is None


@pytest.mark.parametrize("who", ["candidate", "reviewer"])
def test_erasure_removes_cases_decisions_and_other_actor_cache(case, who):
    s = case
    assert decide(s).status_code == 200
    subject = s.candidate_id if who == "candidate" else s.reviewer_id
    with Session(s.hiring.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, deletion(subject))
        assert session.scalar(select(ComplaintCase)) is None
        assert session.scalar(select(ComplaintDecision)) is None
        assert session.scalar(select(Complaint)) is None
        assert not any(
            s.cid in row.response or s.cid in row.operation
            for row in session.scalars(select(IdempotencyRecord))
        )
    assert s.hiring.client.get(s.casepath, headers=s.reviewer).status_code in {404, 409}


def test_moderation_case_backfill_and_guarded_downgrade(case):
    s = case
    config = migration_config(s.hiring.app.state.settings)
    with pytest.raises(RuntimeError):
        command.downgrade(config, "0003_hiring")
    with Session(s.hiring.app.state.engine) as session, session.begin():
        session.query(ComplaintCase).delete()
    command.downgrade(config, "0003_hiring")
    command.upgrade(config, "head")
    assert s.hiring.client.get(s.casepath, headers=s.reviewer).json()["status"] == "open"
    assert s.hiring.client.get("/health/ready").status_code == 200


def test_company_affiliation_blocks_review_even_after_verification_is_rejected(case):
    s = case
    subject = uuid4()
    added = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json={"subject": str(subject), "role": "technical_expert"},
        headers=headers(s.employer_auth, "add", 2),
    )
    assert added.status_code == 201
    rejected = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/verification",
        json={"status": "rejected", "reason": "Synthetic verification withdrawn"},
        headers=headers(s.moderator, "reject", 3),
    )
    assert rejected.status_code == 200
    employee_moderator = s.token(subject, ("company_moderator",), amr=["mfa"])
    assert decide(s, auth=employee_moderator).status_code == 403
