"""Real signed RPC, migrated SQLite and OS fences; synthetic executor/probe only."""

from datetime import UTC, datetime, timedelta
from unittest.mock import Mock
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_code_runner import deletion
from test_event_transport import signatures as signatures_fixture
from test_session_test_pins import setup as pins_setup
from test_session_test_pins import submitted

import reverse_hr.submitted_runner as worker
from reverse_hr.domains.assessment_sessions import StageState
from reverse_hr.domains.code_runner import Output, process_deletion_request
from reverse_hr.domains.coding_workspace import FilesCommand, Snapshot, Workspace
from reverse_hr.domains.evaluation import process_submission
from reverse_hr.domains.evaluation_tests import TestEvidence as Evidence
from reverse_hr.evaluation_access import MaterialAccess
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import canonical, sign
from reverse_hr.sandbox import CleanupUnconfirmed
from reverse_hr.submitted_access import REQUEST, SubmittedAccess, SubmittedRequest
from reverse_hr.test_suites import digest

signatures = signatures_fixture


@pytest.fixture
def setup(service, token, signatures, tmp_path, monkeypatch):
    s = pins_setup.__wrapped__(service, token, signatures, tmp_path, monkeypatch)
    submitted(s)
    s.workspace = service("coding-workspace")
    s.evaluation = service("evaluation")
    source = FilesCommand(files=[{"path": "main.py", "content": "print('candidate')"}])
    with Session(s.assessment.app.state.engine) as session, session.begin():
        session.get(StageState, str(s.stage_id)).digest = digest(source)
    with Session(s.workspace.app.state.engine) as session, session.begin():
        session.add(
            Workspace(
                workspace_id=str(s.workspace_id),
                candidate_id=str(s.candidate),
                session_id=str(s.session_id),
                stage_id=str(s.stage_id),
                format="code",
                version=1,
            )
        )
        session.flush()
        session.add(
            Snapshot(
                snapshot_id=str(s.snapshot_id),
                workspace_id=str(s.workspace_id),
                version=1,
                files=source.model_dump(mode="json")["files"],
                digest=digest(source),
                created_at=datetime.now(UTC),
            )
        )
    s.workspace.app.state.workspace_signatures = signatures["coding-workspace"]
    s.evaluation.app.state.evaluation_signatures = signatures["evaluation"]
    s.refs = {k: getattr(s, "candidate" if k == "candidate_id" else k) for k in worker.REFS} | {
        "node_id": s.node,
        "runtime_fingerprint": s.probe.fingerprint,
    }

    def sender(route, raw, signature, **kwargs):
        client = (
            s.assessment.client
            if route in {"submitted-tests", "evaluation-material"}
            else s.workspace.client
            if route == "submitted-tests-source"
            else s.evaluation.client
        )
        response = client.post(
            "/internal/v1/" + route,
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        if response.status_code != 200:
            raise HTTPException(response.status_code)
        return response.content, response.headers["X-HR-Signature"]

    s.submitted = SubmittedAccess(s.runner.app.state.settings)
    s.submitted._signatures = signatures["code-runner"]
    s.submitted._send = sender
    s.submitted.check = Mock()
    s.workspace.app.state.submitted_access._signatures = signatures["coding-workspace"]
    s.workspace.app.state.submitted_access._send = sender
    access = MaterialAccess(s.evaluation.app.state.settings)
    access._signatures = signatures["evaluation"]
    access.send_material = lambda raw, signature: sender("evaluation-material", raw, signature)
    s.evaluation.app.state.material_access = access
    s.event = EventEnvelope(
        producer="assessment",
        event_type="assessment.stage_submitted.v1",
        aggregate_id=s.stage_id,
        aggregate_version=3,
        correlation_id=uuid4(),
        payload={k: s.refs[k] for k in worker.REFS},
    )
    with Session(s.engine) as session, session.begin():
        worker.process_submission(session, s.event)
    with Session(s.evaluation.app.state.engine) as session, session.begin():
        process_submission(session, s.event, s.evaluation.app.state.processing_access)
    monkeypatch.setattr(worker, "require_execution_ready", lambda *_: None)
    monkeypatch.setattr(worker, "fingerprint", lambda *_: s.probe.fingerprint)
    monkeypatch.setattr(worker, "read_record", lambda *_: s.probe)
    s.executor.execute = Mock(
        return_value=Output(
            status="executed", exit_code=0, stdout=s.definition.cases[0].expected_stdout
        )
    )
    return s


def tick(s):
    return worker.run_one(s.engine, s.submitted, s.executor, s.signatures["code-runner"])


def job(s):
    with Session(s.engine) as session:
        return session.get(worker.SubmittedJob, str(s.stage_id))


def test_actual_signed_source_and_hidden_case_delivery(setup):
    s = setup
    material = s.submitted.fetch(**s.refs)
    source = s.submitted.source(material, **s.refs)
    assert source.files[0].content == "print('candidate')"
    for _ in range(len(s.definition.cases) + 2):
        assert tick(s)
    assert job(s).status == "done"
    assert s.executor.execute.call_count == len(s.definition.cases)
    with Session(s.evaluation.app.state.engine) as session:
        evidence = session.get(Evidence, str(s.stage_id))
        assert evidence and evidence.proof["snapshot_digest"] == digest(source)
        assert evidence.proof["outcomes"][0]["verdict"] == "passed"
        assert "expected_stdout" not in str(evidence.proof)
    assert not tick(s)


@pytest.mark.parametrize(
    "field",
    [
        "candidate_id",
        "session_id",
        "stage_id",
        "workspace_id",
        "snapshot_id",
        "node_id",
        "runtime_fingerprint",
    ],
)
def test_foreign_binding_and_current_runtime_denial(setup, field):
    s = setup
    refs = s.refs | {field: "f" * 64 if field == "runtime_fingerprint" else uuid4()}
    with pytest.raises(HTTPException) as exc:
        s.submitted.fetch(**refs)
    assert exc.value.status_code == 409
    s.assessment.app.state.settings.assessment_trusted_runtimes = []
    with pytest.raises(HTTPException):
        s.submitted.fetch(**s.refs)


def test_nonce_and_signature_context_isolation(setup):
    s = setup
    body = SubmittedRequest(
        **s.refs, requester="code-runner", nonce=uuid4(), issued_at=datetime.now(UTC)
    )
    headers = {
        "X-HR-Signature": sign(s.signatures["code-runner"], REQUEST, body),
        "Content-Type": "application/json",
    }
    assert (
        s.assessment.client.post(
            "/internal/v1/submitted-tests", content=canonical(body), headers=headers
        ).status_code
        == 200
    )
    assert (
        s.assessment.client.post(
            "/internal/v1/submitted-tests", content=canonical(body), headers=headers
        ).status_code
        == 401
    )
    headers["X-HR-Signature"] = sign(s.signatures["code-runner"], b"wrong", body)
    assert (
        s.assessment.client.post(
            "/internal/v1/submitted-tests", content=canonical(body), headers=headers
        ).status_code
        == 401
    )


def test_cleanup_failure_then_recovery_never_reexecutes(setup):
    s = setup
    s.executor.execute.side_effect = CleanupUnconfirmed()
    with pytest.raises(CleanupUnconfirmed):
        tick(s)
    assert tick(s)
    assert job(s).status == "interrupted"
    assert not tick(s)
    assert s.executor.execute.call_count == 1
    with Session(s.engine) as session:
        assert session.scalar(select(worker.SubmittedAttempt)).state == "cleaned"


def test_inconclusive_is_not_zero(setup):
    s = setup
    s.executor.execute.return_value = Output(status="limit_exceeded", reason="time_limit")
    for _ in range(len(s.definition.cases) + 2):
        tick(s)
    assert job(s).proof["outcomes"][0]["verdict"] == "inconclusive"


def test_private_runner_data_erased_and_cleanup_ack_deferred(setup):
    s = setup
    s.executor.execute.side_effect = CleanupUnconfirmed()
    with pytest.raises(CleanupUnconfirmed):
        tick(s)
    with Session(s.engine) as session, session.begin():
        process_deletion_request(session, deletion(s.candidate))
    assert job(s) is None
    assert worker.recover_one(s.engine, s.executor)
    with Session(s.engine) as session:
        assert session.scalar(select(worker.SubmittedAttempt)) is None


def test_lost_delivery_reply_retries_same_proof_without_execution(setup):
    s = setup
    for _ in range(len(s.definition.cases) + 1):
        assert tick(s)
    original = s.submitted._send

    def lose_reply(route, raw, signature, **kwargs):
        result = original(route, raw, signature, **kwargs)
        if route == "submitted-test-result":
            raise HTTPException(503)
        return result

    s.submitted._send = lose_reply
    assert tick(s) and job(s).status == "delivery"
    first = job(s).proof
    s.submitted._send = original
    with Session(s.engine) as session, session.begin():
        session.get(worker.SubmittedJob, str(s.stage_id)).available_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    assert tick(s) and job(s).status == "done"
    assert job(s).proof == first and s.executor.execute.call_count == len(s.definition.cases)


@pytest.mark.parametrize(
    "bad", ["proof_signature", "snapshot", "missing_case", "candidate", "case_hash"]
)
def test_delivery_rejects_untrusted_or_rebound_evidence(setup, bad):
    from reverse_hr.submitted_results import DELIVERY, PROOF, delivery_body
    from reverse_hr.submitted_results import TestProof as Proof

    s = setup
    for _ in range(len(s.definition.cases) + 1):
        tick(s)
    raw = job(s).proof
    proof = Proof.model_validate(raw)
    if bad == "snapshot":
        proof.snapshot_digest = "f" * 64
    elif bad == "candidate":
        proof.candidate_id = uuid4()
    elif bad == "missing_case":
        proof.outcomes[0].criterion_key = "foreign"
    elif bad == "case_hash":
        proof.outcomes[0].case_digest = "f" * 64
    signature = sign(s.signatures["code-runner"], PROOF, proof)
    if bad == "proof_signature":
        signature = sign(s.signatures["assessment"], PROOF, proof)
    body = delivery_body(proof, signature)
    reply = s.evaluation.client.post(
        "/internal/v1/submitted-test-result",
        content=canonical(body),
        headers={
            "X-HR-Signature": sign(s.signatures["code-runner"], DELIVERY, body),
            "Content-Type": "application/json",
        },
    )
    assert reply.status_code in {401, 409}
    with Session(s.evaluation.app.state.engine) as session:
        assert session.get(Evidence, str(s.stage_id)) is None


def test_tampered_capture_cannot_be_signed_as_evidence(setup):
    s = setup
    tick(s)
    with Session(s.engine) as session, session.begin():
        row = session.scalar(select(worker.SubmittedAttempt))
        row.outcome = row.outcome | {"verdict": "failed"}
    assert tick(s) and job(s).status == "blocked"
    assert job(s).proof is None
