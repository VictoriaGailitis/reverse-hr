"""All company content formats, independent bank admission and private cleanup."""

from copy import deepcopy
from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_access import headers
from test_assessment_content import PACKAGE
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture
from test_matching_hiring import setup as market_setup

from reverse_hr.db import IdempotencyRecord
from reverse_hr.domains.assessment import ContentRevision
from reverse_hr.domains.assessment_sessions import process_deletion_request
from reverse_hr.domains.company_tasks import CompanyProposal
from reverse_hr.market_access import MarketAccess
from reverse_hr.migrate import migration_config
from reverse_hr.processing_access import ProcessingAccess

signatures = signatures_fixture
setup = market_setup


@pytest.fixture
def company(setup, service):
    s = setup
    s.assessment = service("assessment")
    for cls, field in ((ProcessingAccess, "processing_access"), (MarketAccess, "market_access")):
        access = cls(s.assessment.app.state.settings)
        access._signatures, access._send = s.signatures["assessment"], s.sender
        setattr(s.assessment.app.state, field, access)
    s.reviewer = s.token(uuid4(), ("content_admin",), amr=["mfa"])
    return s


def package(format="code", evidence=None):
    content = deepcopy(PACKAGE)
    content["tasks"][0]["format"] = format
    content["tasks"][0]["rubric"][0]["evidence"] = (
        evidence
        or {
            "code": "test_result",
            "sql": "test_result",
            "vcv": "artifact",
            "voice": "timestamped_recording",
            "whiteboard": "board_snapshot",
        }[format]
    )
    return content


def create(s, format="code", auth=None, key="proposal", content=None):
    return s.assessment.client.post(
        "/v1/company-task-proposals",
        json={
            "organization_id": s.organization_id,
            "name": "Synthetic company task",
            "content": content or package(format),
        },
        headers=headers(auth or s.employer_auth, key),
    )


def submit(s, row, key="submit"):
    return s.assessment.client.post(
        f"/v1/company-task-proposals/{row['proposal_id']}/submit",
        headers=headers(s.employer_auth, key, row["version"]),
    )


def review(s, row, auth=None, outcome="approve", digest=None, key="review"):
    return s.assessment.client.post(
        f"/v1/company-task-proposals/{row['proposal_id']}/review",
        json={
            "outcome": outcome,
            "digest": digest or row["digest"],
            "reason": "Synthetic independent review",
        },
        headers=headers(auth or s.reviewer, key, row["version"]),
    )


@pytest.mark.parametrize("format", ["code", "sql", "vcv", "voice", "whiteboard"])
def test_all_content_formats_independent_publication_and_withdrawal(company, format):
    s = company
    response = create(s, format)
    assert response.status_code == 201, response.text
    row = response.json()
    assert row["status"] == "draft" and row["content"]["demo"]
    assert row["content"]["source_dataset"] == "company:" + s.organization_id
    assert create(s, format).json() == row
    assert (
        s.assessment.client.get(
            f"/v1/company-task-proposals/{row['proposal_id']}", headers=s.reviewer
        ).status_code
        == 409
    )
    submitted = submit(s, row)
    assert submitted.status_code == 200
    row = submitted.json()
    assert review(s, row, digest="0" * 64).status_code == 409
    approved = review(s, row)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved" and approved.json()["bank_status"] == "published"
    assert review(s, row).json() == approved.json()
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["confirmed_grade"]
        == "middle"
    )
    assert review(s, row, key="second").status_code == 409
    with Session(s.assessment.app.state.engine) as session:
        versions = list(session.scalars(select(ContentRevision)))
        assert len(versions) == 1 and versions[0].content["tasks"][0]["format"] == format
        assert versions[0].created_by == str(s.recruiter_id)
        assert not any(
            "Synthetic reference" in cached.response
            for cached in session.scalars(select(IdempotencyRecord))
        )
    row = approved.json()
    withdrawn = s.assessment.client.post(
        f"/v1/company-task-proposals/{row['proposal_id']}/withdraw",
        json={"reason": "Withdraw this version"},
        headers=headers(s.employer_auth, "withdraw", row["version"]),
    )
    assert withdrawn.status_code == 200 and withdrawn.json()["bank_status"] == "retired"


@pytest.mark.parametrize(
    "format,evidence",
    [
        ("code", "board_snapshot"),
        ("sql", "timestamped_recording"),
        ("vcv", "test_result"),
        ("voice", "artifact"),
        ("whiteboard", "test_result"),
    ],
)
def test_each_format_rejects_incompatible_evidence(company, format, evidence):
    assert create(company, content=package(format, evidence)).status_code == 422


def test_mixed_package_all_formats_and_bounded_validators(company):
    s = company
    content = package()
    content["tasks"] = []
    for format in ("code", "sql", "vcv", "voice", "whiteboard"):
        task = package(format)["tasks"][0]
        task["key"] = format
        content["tasks"].append(task)
    assert create(s, content=content).status_code == 201
    bad = deepcopy(content)
    bad["tasks"][0]["rubric"][0]["points"] = 99
    assert create(s, content=bad, key="points").status_code == 422
    bad = deepcopy(content)
    for task in bad["tasks"]:
        task["duration_seconds"] = 3600
    assert create(s, content=bad, key="duration").status_code == 422
    bad = deepcopy(content)
    bad["demo"] = False
    assert create(s, content=bad, key="production").status_code == 422


def test_draft_edit_submit_freezes_content_and_queue(company):
    s = company
    row = create(s).json()
    path = "/v1/company-task-proposals/" + row["proposal_id"]
    changed = s.assessment.client.put(
        path,
        json={"organization_id": s.organization_id, "name": "Edited", "content": package("voice")},
        headers=headers(s.employer_auth, "edit", 1),
    )
    assert changed.status_code == 200
    assert changed.json()["digest"] != row["digest"]
    row = submit(s, changed.json()).json()
    assert (
        s.assessment.client.put(
            path,
            json={
                "organization_id": s.organization_id,
                "name": "Edit submitted",
                "content": package(),
            },
            headers=headers(s.employer_auth, "late", row["version"]),
        ).status_code
        == 409
    )
    queue = s.assessment.client.get("/v1/company-task-proposals", headers=s.reviewer)
    assert queue.status_code == 200 and len(queue.json()) == 1
    assert "content" not in queue.json()[0]
    assert review(s, row, outcome="reject").json()["status"] == "rejected"
    with Session(s.assessment.app.state.engine) as session:
        assert session.scalar(select(ContentRevision)) is None


def test_self_review_roles_mfa_and_technical_expert_access(company):
    s = company
    subject = uuid4()
    expert = s.token(subject, ("employer",))
    member = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json={"subject": str(subject), "role": "technical_expert"},
        headers=headers(s.employer_auth, "expert", 2),
    )
    assert member.status_code == 201
    response = create(s, auth=expert)
    assert response.status_code == 201, response.text
    row = submit(s, response.json()).json()
    self_reviewer = s.token(subject, ("content_admin",), amr=["mfa"])
    assert review(s, row, auth=self_reviewer).status_code == 403
    assert review(s, row, auth=s.token(uuid4(), ("content_admin",))).status_code == 403
    colleague = s.token(s.recruiter_id, ("content_admin",), amr=["mfa"])
    assert review(s, row, auth=colleague).status_code == 403
    assert create(s, auth=s.token(uuid4(), ("employer",)), key="outsider").status_code == 409
    assert (
        s.assessment.client.get(
            "/v1/company-task-proposals/" + row["proposal_id"], headers=s.auth
        ).status_code
        == 403
    )


@pytest.mark.parametrize("published", [False, True])
def test_company_contributor_erasure_purges_private_copy_and_restricts_bank(company, published):
    s = company
    row = create(s).json()
    if published:
        row = review(s, submit(s, row).json()).json()
    with Session(s.assessment.app.state.engine) as session, session.begin():
        assert process_deletion_request(session, deletion(s.recruiter_id))
        assert session.scalar(select(CompanyProposal)) is None
        assert not any(
            row["proposal_id"] in cached.response or row["proposal_id"] in cached.operation
            for cached in session.scalars(select(IdempotencyRecord))
        )
    assert (
        s.assessment.client.get(
            "/v1/company-task-proposals/" + row["proposal_id"], headers=s.reviewer
        ).status_code
        == 404
    )
    assert s.assessment.client.get("/health/ready").status_code == 200
    if published:
        assert (
            s.assessment.client.get(
                "/v1/content-versions/" + row["revision_id"], headers=s.reviewer
            ).status_code
            == 409
        )
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.assessment.app.state.settings), "base")


def test_unavailable_employer_never_replays_private_proposal(company):
    s = company
    assert create(s).status_code == 201

    def unavailable(*args, **kwargs):
        raise HTTPException(503)

    s.assessment.app.state.market_access._send = unavailable
    assert create(s).status_code == 503


def test_populated_proposal_downgrade_protects_data(company):
    s = company
    row = create(s).json()
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(s.assessment.app.state.settings), "0011_assessment")
    assert (
        s.assessment.client.get(
            "/v1/company-task-proposals/" + row["proposal_id"], headers=s.employer_auth
        ).status_code
        == 200
    )


def test_another_employee_cannot_rewrite_proposal_author_content(company):
    s = company
    row = create(s).json()
    subject = uuid4()
    member = s.employer.client.post(
        f"/v1/organizations/{s.organization_id}/members",
        json={"subject": str(subject), "role": "technical_expert"},
        headers=headers(s.employer_auth, "other", 2),
    )
    assert member.status_code == 201
    result = s.assessment.client.put(
        "/v1/company-task-proposals/" + row["proposal_id"],
        json={
            "organization_id": s.organization_id,
            "name": "Changed by somebody else",
            "content": package("whiteboard"),
        },
        headers=headers(s.token(subject, ("employer",)), "edit", 1),
    )
    assert result.status_code == 403
    assert (
        s.assessment.client.get(
            "/v1/company-task-proposals/" + row["proposal_id"], headers=s.employer_auth
        ).json()["digest"]
        == row["digest"]
    )
