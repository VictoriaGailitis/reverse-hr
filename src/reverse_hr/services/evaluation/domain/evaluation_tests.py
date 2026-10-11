"""Authenticated hidden-test evidence; source stdout is never a test certificate."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import JSON, DateTime, String, delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.test_suites import digest
from reverse_hr.protocols.evaluation_access import PinnedMaterial
from reverse_hr.protocols.submitted_results import (
    DELIVERY,
    PROOF,
    RECEIPT,
    ResultDelivery,
    ResultReceipt,
    TestProof,
)
from reverse_hr.services.evaluation.domain.evaluation import (
    EvaluationBase,
    EvaluationIntake,
    subject_lock,
)
from reverse_hr.shared.db import enqueue
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, fresh, sign, verify


class TestEvidence(EvaluationBase):
    __tablename__ = "evaluation_test_evidence"
    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    proof: Mapped[dict] = mapped_column(JSON)
    signature: Mapped[str] = mapped_column(String(128))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ResultNonce(EvaluationBase):
    __tablename__ = "evaluation_result_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


router = APIRouter(prefix="/internal/v1", tags=["internal-test-results"])


def validate_proof(proof, material):
    if (
        proof.binding != material.test_suite
        or proof.snapshot_version != material.snapshot_version
        or proof.snapshot_digest != material.snapshot_digest
        or proof.completed_at - proof.probe.checked_at > timedelta(hours=24)
    ):
        raise HTTPException(409, "Test proof differs from submitted material")
    keys = {c.key for c in material.task.rubric if c.evidence == "test_result"}
    expected = {(c.case_key, c.criterion_key, c.case_digest) for c in material.test_cases}
    actual = {(c.case_key, c.criterion_key, c.case_digest) for c in proof.outcomes}
    if not expected or expected != actual or {o.criterion_key for o in proof.outcomes} != keys:
        raise HTTPException(409, "Incomplete test evidence")


def test_points(session, row, signatures):
    evidence = session.get(TestEvidence, row.stage_id)
    if evidence is None:
        return {}, None
    proof = TestProof.model_validate(evidence.proof)
    verify(signatures, "code-runner", evidence.signature, PROOF, proof)
    material = PinnedMaterial.model_validate(row.material)
    validate_proof(proof, material)
    if any(
        str(getattr(proof, k)) != getattr(row, k)
        for k in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
    ):
        raise HTTPException(409)
    points = {}
    for criterion in material.task.rubric:
        if criterion.evidence == "test_result":
            cases = [o for o in proof.outcomes if o.criterion_key == criterion.key]
            points[criterion.key] = (
                None
                if any(o.verdict == "inconclusive" for o in cases)
                else criterion.points * sum(o.verdict == "passed" for o in cases) // len(cases)
            )
    return points, digest(proof)


@router.post("/submitted-test-result", response_model=ResultReceipt)
def receive_result(
    request: Request,
    body: ResultDelivery,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "evaluation_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, body.requester, signature, DELIVERY, body)
        verify(signatures, "code-runner", body.proof_signature, PROOF, body.proof)
    except Exception as exc:
        raise HTTPException(401) from exc
    proof = body.proof
    refs = {
        k: getattr(proof, k)
        for k in ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")
    }
    # Network calls precede local row locks; final consent check is serialized with deletion.
    material = request.app.state.material_access.fetch(**refs)
    validate_proof(proof, material)
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(ResultNonce).where(ResultNonce.expires_at < now))
            session.add(ResultNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            subject = subject_lock(session, proof.candidate_id, allow_blocked=True)
            row = session.scalar(
                select(EvaluationIntake)
                .where(EvaluationIntake.stage_id == str(proof.stage_id))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            allowed = bool(
                not subject.blocked
                and row
                and all(getattr(row, k) == str(v) for k, v in refs.items())
            )
            if allowed:
                request.app.state.processing_access.check_assessment(
                    proof.candidate_id, material.consent_id
                )
                if row.material is not None and row.material != material.model_dump(mode="json"):
                    raise HTTPException(409)
                existing = session.get(TestEvidence, row.stage_id)
                if existing and (
                    existing.proof != proof.model_dump(mode="json")
                    or existing.signature != body.proof_signature
                ):
                    raise HTTPException(409)
                if not existing:
                    session.add(
                        TestEvidence(
                            stage_id=row.stage_id,
                            candidate_id=row.candidate_id,
                            proof=proof.model_dump(mode="json"),
                            signature=body.proof_signature,
                            received_at=now,
                        )
                    )
                    enqueue(
                        session,
                        EventEnvelope(
                            event_type="evaluation.test_evidence_received.v1",
                            producer="evaluation",
                            correlation_id=uuid4(),
                            aggregate_id=proof.stage_id,
                            aggregate_version=row.version,
                            payload=refs,
                        ),
                    )
            receipt = ResultReceipt(
                candidate_id=body.candidate_id,
                nonce=body.nonce,
                issued_at=datetime.now(UTC),
                stage_id=proof.stage_id,
                proof_digest=digest(proof),
                allowed=allowed,
            )
            raw, signed = canonical(receipt), sign(signatures, RECEIPT, receipt)
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
