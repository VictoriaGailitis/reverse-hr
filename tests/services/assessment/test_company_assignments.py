"""Company assignment admission and actual signed evidence/results in all five formats."""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.protocols.evaluation_access import MaterialAccess
from reverse_hr.protocols.evaluation_artifact_access import ArtifactAccess, ArtifactPermitAccess
from reverse_hr.protocols.grade_access import GradeAccess
from reverse_hr.protocols.market_access import MarketAccess
from reverse_hr.protocols.practical_receipts import PracticalReceiptAccess
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.protocols.recording_access import RecordingAccess
from reverse_hr.protocols.snapshot_access import SnapshotAccess
from reverse_hr.protocols.stage_access import StageAccess
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PracticalSession,
    process_deletion_request,
)
from reverse_hr.services.assessment.domain.company_assignments import CompanyAssignment
from reverse_hr.services.evaluation.domain.evaluation import process_submission
from reverse_hr.services.evaluation.evaluation_artifacts import collect_one
from reverse_hr.services.evaluation.evaluation_material import prepare_one
from reverse_hr.services.media.media_validation import MediaValidation
from reverse_hr.shared.db import IdempotencyRecord, Outbox
from tests.integration.test_matching_hiring import consent
from tests.integration.test_matching_hiring import setup as market_setup
from tests.integration.test_practical_environments import prepared
from tests.integration.test_practical_environments import submit as submit_practical
from tests.integration.test_practical_evaluation import Speech, decision, transcribe
from tests.services.assessment.test_company_tasks import company as company_fixture
from tests.services.assessment.test_company_tasks import create, package, review, submit
from tests.shared.test_access import headers
from tests.shared.test_event_transport import signatures as signatures_fixture

company = company_fixture
setup = market_setup
signatures = signatures_fixture


def assigned(s, format="code", key="assign"):
    content = package(format, "artifact" if format in {"code", "sql"} else None)
    row = create(s, format, content=content).json()
    row = review(s, submit(s, row).json()).json()
    plan = s.assessment.client.post(
        "/v1/assessment-plans",
        headers=headers(s.reviewer, "plan"),
        json={
            "name": "Company plan",
            "revision_ids": [row["revision_id"]],
            "reason": "Reviewed plan",
        },
    )
    assert plan.status_code == 201, plan.text
    s.proposal, s.plan = row, plan.json()
    s.assign_body = dict(
        organization_id=s.organization_id,
        candidate_id=str(s.candidate_id),
        proposal_id=row["proposal_id"],
        plan_version_id=s.plan["plan_version_id"],
    )
    reply = s.assessment.client.post(
        "/v1/company-assignments", json=s.assign_body, headers=headers(s.employer_auth, key)
    )
    assert reply.status_code == 201, reply.text
    s.assignment = reply.json()
    s.assignment_path = "/v1/company-assignments/" + s.assignment["assignment_id"]
    return s.assignment


def grant(s, **refs):
    s.result_consent = consent(s, "company_result_disclosure")
    reply = s.privacy.client.post(
        "/v1/company-result-grants",
        headers=headers(s.auth, "grant"),
        json=dict(
            assignment_id=s.assignment["assignment_id"],
            organization_id=s.organization_id,
            consent_id=s.result_consent,
        )
        | refs,
    )
    assert reply.status_code == 201, reply.text
    s.grant = reply.json()
    return s.grant


def accept(s, **changes):
    if not hasattr(s, "assessment_consent"):
        s.assessment_consent = consent(s, "assessment")
    s.accept_body = (
        dict(assessment_consent_id=s.assessment_consent, result_grant_id=s.grant["grant_id"])
        | changes
    )
    return s.assessment.client.post(
        s.assignment_path + "/accept", json=s.accept_body, headers=headers(s.auth, "accept", 1)
    )


def test_admission_scope_replays_decline_and_general_grade(company):
    s = company
    assignment = assigned(s)
    assert assignment["result_recipient"] == s.organization_id
    assert not assignment["affects_general_grade"] and not assignment["reveals_contacts"]
    assert (
        s.assessment.client.post(
            "/v1/company-assignments",
            json=s.assign_body,
            headers=headers(s.employer_auth, "assign"),
        ).json()
        == assignment
    )
    assert (
        s.assessment.client.post(
            "/v1/company-assignments",
            json=s.assign_body,
            headers=headers(s.employer_auth, "duplicate"),
        ).status_code
        == 409
    )
    grant(s, organization_id=str(uuid4()))
    assert accept(s).status_code == 409
    assert accept(s, result_grant_id=str(uuid4())).status_code == 409
    declined = s.assessment.client.post(
        s.assignment_path + "/decline", headers=headers(s.auth, "decline", 1)
    )
    assert declined.status_code == 200 and declined.json()["status"] == "declined"
    assert (
        s.assessment.client.post(
            s.assignment_path + "/decline", headers=headers(s.auth, "decline", 1)
        ).json()
        == declined.json()
    )
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["confirmed_grade"]
        == "middle"
    )
    assert len(s.assessment.client.get("/v1/company-assignments", headers=s.auth).json()) == 1
    assert s.assessment.client.get(s.assignment_path, headers=s.token()).status_code == 403


@pytest.mark.parametrize("closure", ["expire", "withdraw", "retire", "revoke", "consent"])
def test_new_admission_closes_on_expiry_retirement_or_revocation(company, closure):
    s = company
    assigned(s)
    grant(s)
    if closure == "expire":
        with Session(s.assessment.app.state.engine) as db, db.begin():
            db.get(CompanyAssignment, s.assignment["assignment_id"]).expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
    elif closure == "withdraw":
        assert (
            s.assessment.client.post(
                f"/v1/company-task-proposals/{s.proposal['proposal_id']}/withdraw",
                json={"reason": "Retire"},
                headers=headers(s.employer_auth, "withdraw", s.proposal["version"]),
            ).status_code
            == 200
        )
    elif closure == "retire":
        assert (
            s.assessment.client.post(
                f"/v1/assessment-plans/{s.plan['plan_version_id']}/retire",
                json={"reason": "Retire"},
                headers=headers(s.reviewer, "retire", 1),
            ).status_code
            == 200
        )
    elif closure == "revoke":
        assert (
            s.assessment.client.post(
                s.assignment_path + "/revoke", headers=headers(s.employer_auth, "revoke", 1)
            ).status_code
            == 200
        )
    else:
        assert (
            s.privacy.client.post(
                f"/v1/consents/{s.result_consent}/revoke", headers=headers(s.auth, "revoke", 1)
            ).status_code
            == 200
        )
    assert accept(s).status_code == 409
    with Session(s.assessment.app.state.engine) as db:
        assert db.scalar(select(PracticalSession)) is None


@pytest.fixture(params=["code", "sql", "voice", "vcv", "whiteboard"])
def completed(company, service, request):
    s = company
    s.format, s.subject = request.param, s.candidate_id
    assigned(s, s.format)
    grant(s)
    reply = accept(s)
    assert reply.status_code == 201, reply.text
    assert accept(s).json() == reply.json()
    s.session_id, s.stage_id = reply.json()["session_id"], reply.json()["stages"][0]["stage_id"]
    s.path = "/v1/assessment-sessions/" + s.session_id
    s.name = (
        "coding-workspace"
        if s.format in {"code", "sql"}
        else "whiteboard"
        if s.format == "whiteboard"
        else "media"
    )
    s.env, s.evaluation = service(s.name), service("evaluation")
    targets = {
        "assessment": s.assessment,
        "privacy": s.privacy,
        "employer": s.employer,
        "evaluation": s.evaluation,
        s.name: s.env,
    }

    def sender(endpoint, raw, signature, *, origin=None, **kwargs):
        owner = origin.split("//")[1].split(":")[0] if origin else "privacy"
        reply = targets[owner].client.post(
            "/internal/v1/" + endpoint,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if reply.status_code != 200:
            raise HTTPException(reply.status_code, reply.text)
        return reply.content, reply.headers["X-HR-Signature"]

    def wire(target, cls, field, owner):
        access = cls(target.app.state.settings)
        access._signatures, access._send = s.signatures[owner], sender
        setattr(target.app.state, field, access)
        return access

    for name, target in targets.items():
        setattr(target.app.state, name.replace("-", "_") + "_signatures", s.signatures[name])
    s.env.app.state.practical_signatures = s.signatures[s.name]
    s.env.app.state.workspace_signatures = s.signatures[s.name]
    wire(s.assessment, GradeAccess, "grade_access", "assessment")
    wire(s.evaluation, ProcessingAccess, "processing_access", "evaluation")
    wire(s.evaluation, MarketAccess, "market_access", "evaluation")
    wire(s.env, ProcessingAccess, "processing_access", s.name)
    s.stage_access = wire(s.env, StageAccess, "stage_access", s.name)
    material = wire(s.evaluation, MaterialAccess, "material_access", "evaluation")
    material.send_material = lambda raw, sig: sender(
        "evaluation-material", raw, sig, origin="http://assessment:8000"
    )
    artifact = wire(s.evaluation, ArtifactAccess, "artifact_access", "evaluation")
    artifact.send_artifact = lambda raw, sig: sender(
        "evaluation-artifact", raw, sig, origin=f"http://{s.name}:8000"
    )
    permit = wire(s.env, ArtifactPermitAccess, "artifact_permit_access", s.name)
    permit.send_permit = lambda raw, sig: sender(
        "evaluation-artifact-admission", raw, sig, origin="http://assessment:8000"
    )
    assert (
        s.assessment.client.post(s.path + "/start", headers=headers(s.auth, "start", 1)).status_code
        == 200
    )
    assert (
        s.assessment.client.post(
            s.path + f"/stages/{s.stage_id}/start", headers=headers(s.auth, "stage", 2)
        ).status_code
        == 200
    )
    if s.name == "coding-workspace":
        receipt = wire(s.assessment, SnapshotAccess, "snapshot_access", "assessment")
        receipt.send_receipt = lambda raw, sig: sender(
            "snapshot-receipt", raw, sig, origin="http://coding-workspace:8000"
        )
        reply = s.env.client.post(
            "/v1/workspaces",
            headers=headers(s.auth, "workspace"),
            json=dict(
                session_id=s.session_id,
                stage_id=s.stage_id,
                files=[
                    {
                        "path": "main.py" if s.format == "code" else "query.sql",
                        "content": "synthetic candidate answer",
                    }
                ],
            ),
        )
        assert reply.status_code == 201, reply.text
        s.artifact = reply.json()
        s.ref = s.artifact["workspace_id"]
    else:
        receipt = wire(
            s.assessment, PracticalReceiptAccess, "practical_receipt_access", "assessment"
        )
        receipt._send = lambda endpoint, raw, sig, **kwargs: sender(
            endpoint, raw, sig, origin=f"http://{s.name}:8000"
        )
        if s.name == "media":
            s.recording_consent = consent(s, "recording")
            wire(s.env, RecordingAccess, "recording_access", "media")
            s.raw = b"\x1aE\xdf\xa3" + b"synthetic" * 33000
            s.env.app.state.media_validator = SimpleNamespace(
                validate=lambda *_: MediaValidation(
                    validator="test-only",
                    duration_ms=5000,
                    audio_codec="opus",
                    sample_rate=48000,
                    channels=1,
                )
            )
        s.ref, s.artifact = prepared(s)
    assert submit_practical(s, s.ref, s.artifact).status_code == 200
    if s.name == "media":
        assert transcribe(s, Speech())
    with Session(s.assessment.app.state.engine) as db:
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "assessment.stage_submitted.v1"
        )
    with Session(s.evaluation.app.state.engine) as db, db.begin():
        assert process_submission(db, event, s.evaluation.app.state.processing_access)
    assert prepare_one(s.evaluation.app.state.engine, material)
    assert collect_one(s.evaluation.app.state.engine, material, artifact)
    s.review_auth = s.token(uuid4(), ("assessment_reviewer",), amr=["mfa"])
    s.review_path = "/v1/evaluation-reviews/stages/" + s.stage_id
    workspace = s.evaluation.client.get(s.review_path, headers=s.review_auth)
    assert workspace.status_code == 200, workspace.text
    s.workspace = workspace.json()
    assert s.workspace["material"]["company_organization_id"] == s.organization_id
    return s


def review_body(s):
    if s.name == "coding-workspace":
        import hashlib

        file = s.workspace["source"]["files"][0]
        criterion = dict(
            criterion_key=s.workspace["material"]["task"]["rubric"][0]["key"],
            points=80,
            reason="Evidence reviewed",
            citations=[
                dict(
                    path=file["path"],
                    file_digest=hashlib.sha256(file["content"].encode()).hexdigest(),
                    start_line=1,
                    end_line=1,
                )
            ],
        )
    else:
        criterion = decision(s)
    return {"decisions": [criterion], "reason": "Independent review"}


def confirm(s):
    reply = s.evaluation.client.post(
        s.review_path + "/reviews",
        headers=headers(s.review_auth, "review", s.workspace["version"]),
        json=review_body(s),
    )
    assert reply.status_code == 200, reply.text


def test_all_formats_company_receives_only_reviewed_scores_and_grant_revokes(completed):
    s = completed
    path = s.assignment_path + "/result"
    reply = s.assessment.client.get(path, headers=s.employer_auth)
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "review_pending" and reply.json()["stages"] == []
    assert (
        s.assessment.client.post(
            s.assignment_path + "/complete", headers=headers(s.auth, "complete", 2)
        ).status_code
        == 409
    )
    confirm(s)
    complete = s.assessment.client.post(
        s.assignment_path + "/complete", headers=headers(s.auth, "complete", 2)
    )
    assert complete.status_code == 200, complete.text
    assert complete.json()["status"] == "completed"
    assert (
        s.assessment.client.post(
            s.assignment_path + "/complete", headers=headers(s.auth, "complete", 2)
        ).json()
        == complete.json()
    )
    reply = s.assessment.client.get(path, headers=s.employer_auth)
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "reviewed" and reply.json()["stages"][0]["score"] == 80
    assert s.assessment.client.get(path, headers=s.auth).json() == reply.json()
    for private in (
        "source",
        "reference_answer",
        "citations",
        "reviewer_id",
        "email",
        "phone",
        "transcript",
        "snapshot_id",
        "synthetic candidate answer",
    ):
        assert private not in reply.text
    assert (
        s.candidate.client.get("/v1/candidates/me", headers=s.auth).json()["confirmed_grade"]
        == "middle"
    )
    with Session(s.assessment.app.state.engine) as db:
        assert db.get(PracticalSession, s.session_id).grade_policy_id is None
        assert not any(
            r.envelope["event_type"] == "assessment.grade_decision_recorded.v1"
            for r in db.scalars(select(Outbox))
        )
    assert (
        s.privacy.client.post(
            f"/v1/company-result-grants/{s.grant['grant_id']}/revoke",
            headers=headers(s.auth, "revoke", 1),
        ).status_code
        == 200
    )
    assert s.assessment.client.get(path, headers=s.employer_auth).status_code == 409
    assert accept(s).status_code == 409  # Cached acceptance cannot resurrect the grant.
    assert s.assessment.client.get(path, headers=s.auth).status_code == 200


def test_company_member_cannot_review_own_assignment(completed):
    s = completed
    insider = s.token(s.recruiter_id, ("assessment_reviewer",), amr=["mfa"])
    assert s.evaluation.client.get(s.review_path, headers=insider).status_code == 403
    assert (
        s.evaluation.client.post(
            s.review_path + "/reviews",
            headers=headers(insider, "insider", s.workspace["version"]),
            json=review_body(s),
        ).status_code
        == 403
    )


def test_privacy_purges_assignments_caches_and_denies_replay(company):
    from tests.services.code_runner.test_code_runner import deletion

    s = company
    assigned(s)
    grant(s)
    assert accept(s).status_code == 201
    with Session(s.assessment.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, deletion(s.candidate_id))
    with Session(s.assessment.app.state.engine) as db:
        assert db.scalar(select(CompanyAssignment)) is None
        assert not any(
            s.assignment["assignment_id"] in r.response
            for r in db.scalars(select(IdempotencyRecord))
        )
    assert s.assessment.client.get(s.assignment_path, headers=s.employer_auth).status_code == 404
    assert accept(s).status_code == 404


@pytest.mark.parametrize("failure", ["consent", "expire", "unavailable", "signature", "member"])
def test_result_requires_fresh_permissions_and_authenticated_scores(completed, failure):
    s = completed
    confirm(s)
    if failure == "consent":
        assert (
            s.privacy.client.post(
                f"/v1/consents/{s.result_consent}/revoke", headers=headers(s.auth, "revoke", 1)
            ).status_code
            == 200
        )
    elif failure == "expire":
        from reverse_hr.services.privacy.domain.privacy_company_results import CompanyResultGrant

        with Session(s.privacy.app.state.engine) as db, db.begin():
            db.get(CompanyResultGrant, s.grant["grant_id"]).expires_at = datetime.now(
                UTC
            ) - timedelta(seconds=1)
    elif failure == "unavailable":
        original = s.assessment.app.state.market_access._send

        def offline(endpoint, *args, **kwargs):
            if endpoint == "market/company-result-permission":
                raise OSError("Unavailable")
            return original(endpoint, *args, **kwargs)

        s.assessment.app.state.market_access._send = offline
    elif failure == "signature":
        original = s.assessment.app.state.grade_access._send

        def tampered(*args, **kwargs):
            raw, _ = original(*args, **kwargs)
            return raw, "0" * 128

        s.assessment.app.state.grade_access._send = tampered
    else:
        from reverse_hr.services.employer.domain.employer import Membership

        with Session(s.employer.app.state.engine) as db, db.begin():
            row = db.scalar(select(Membership).where(Membership.subject == str(s.recruiter_id)))
            row.status = "revoked"
    expected = 503 if failure in {"unavailable", "signature"} else 409
    assert (
        s.assessment.client.get(s.assignment_path + "/result", headers=s.employer_auth).status_code
        == expected
    )


def test_deleted_assigner_keeps_candidate_session_recipient_binding(company):
    from tests.services.code_runner.test_code_runner import deletion

    s = company
    assigned(s)
    grant(s)
    reply = accept(s)
    assert reply.status_code == 201
    with Session(s.assessment.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, deletion(s.recruiter_id))
    with Session(s.assessment.app.state.engine) as db:
        row = db.get(CompanyAssignment, s.assignment["assignment_id"])
        assert (
            row.organization_id == s.organization_id
            and row.session_id == reply.json()["session_id"]
        )
    assert s.assessment.client.get(s.assignment_path, headers=s.employer_auth).status_code == 409


def test_company_admission_preserves_runtime_admitted_private_suite_pins(
    company, service, token, signatures, tmp_path, monkeypatch
):
    from reverse_hr.contracts.session_test_pins import stored_pins
    from reverse_hr.contracts.test_suites import digest
    from reverse_hr.services.assessment.domain.assessment import ContentPackage, ContentRevision
    from reverse_hr.services.assessment.domain.assessment_sessions import PlanVersion
    from reverse_hr.services.assessment.domain.company_tasks import CompanyProposal
    from tests.services.assessment.test_session_test_pins import setup as pins_setup

    s = company
    pinned = pins_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    s.assessment.app.state.assessment_signatures = signatures["assessment"]
    s.assessment.app.state.settings.assessment_trusted_runtimes = [pinned.policy]
    proposal_id = str(uuid4())
    # Bind the previously approved synthetic catalogue fixture; constructor publication
    # itself is covered by the all-format scenario above.
    with Session(s.assessment.app.state.engine) as db, db.begin():
        revision = db.get(ContentRevision, pinned.selection["revision_id"])
        db.add(
            CompanyProposal(
                proposal_id=proposal_id,
                organization_id=s.organization_id,
                created_by=str(s.recruiter_id),
                name="Approved pinned task",
                content=revision.content,
                digest=digest(ContentPackage.model_validate(revision.content)),
                status="approved",
                version=3,
                created_at=datetime.now(UTC),
                reviewed_by=revision.reviewed_by,
                revision_id=revision.revision_id,
            )
        )
    reply = s.assessment.client.post(
        "/v1/company-assignments",
        headers=headers(s.employer_auth, "assign"),
        json=dict(
            organization_id=s.organization_id,
            candidate_id=str(s.candidate_id),
            proposal_id=proposal_id,
            plan_version_id=pinned.version["plan_version_id"],
        ),
    )
    assert reply.status_code == 201, reply.text
    s.assignment, s.assignment_path = (
        reply.json(),
        "/v1/company-assignments/" + reply.json()["assignment_id"],
    )
    grant(s)
    reply = accept(s)
    assert reply.status_code == 201, reply.text
    with Session(s.assessment.app.state.engine) as db:
        plan = stored_pins(db.get(PlanVersion, pinned.version["plan_version_id"]))
        practical = db.get(PracticalSession, reply.json()["session_id"])
        actual = stored_pins(practical, for_session=True)
        assert actual[0].pin == plan[0].pin
        assert actual[0].validation_id == plan[0].validation_id
        assert str(actual[0].stage_id) == reply.json()["stages"][0]["stage_id"]
        assert practical.grade_policy_id is None


def test_scoped_permission_signature_nonce_and_cross_assignment_binding(company):
    from reverse_hr.contracts.market_contracts import MarketRequest
    from reverse_hr.protocols.market_access import context
    from reverse_hr.shared.signing import canonical, sign

    s = company
    assigned(s)
    grant(s)
    body = MarketRequest(
        requester="assessment",
        purpose="company-result-permission",
        nonce=uuid4(),
        issued_at=datetime.now(UTC),
        candidate_id=s.candidate_id,
        organization_id=s.organization_id,
        assignment_id=s.assignment["assignment_id"],
        result_grant_id=s.grant["grant_id"],
    )

    def post(value, signature=None):
        return s.privacy.client.post(
            "/internal/v1/market/company-result-permission",
            content=canonical(value),
            headers={
                "Content-Type": "application/json",
                "X-HR-Signature": signature
                or sign(
                    s.signatures[value.requester],
                    context("privacy", value.purpose, "request"),
                    value,
                ),
            },
        )

    assert post(body).json()["allowed"] is True
    assert post(body).status_code == 401
    foreign = body.model_copy(update={"nonce": uuid4(), "assignment_id": uuid4()})
    assert post(foreign).json()["allowed"] is False
    assert post(body.model_copy(update={"nonce": uuid4()}), "0" * 128).status_code == 401
    assert (
        post(body.model_copy(update={"nonce": uuid4(), "requester": "hiring"})).status_code == 401
    )


def test_common_material_serialization_preserves_existing_evaluation_records():
    from reverse_hr.protocols.evaluation_access import PinnedMaterial
    from reverse_hr.shared.signing import canonical

    content = package("code", "artifact")
    material = PinnedMaterial(
        consent_id=uuid4(),
        plan_version_id=uuid4(),
        revision_id=uuid4(),
        content_digest="a" * 64,
        task=content["tasks"][0],
        competencies=content["competencies"],
        snapshot_version=1,
        snapshot_digest="b" * 64,
    )
    stored = material.model_dump(mode="json")
    assert "company_organization_id" not in stored
    assert PinnedMaterial.model_validate(stored) == material
    assert canonical(PinnedMaterial.model_validate(stored)) == canonical(material)
