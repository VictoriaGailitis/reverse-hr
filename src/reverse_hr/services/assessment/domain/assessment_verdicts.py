"""Signature-verified verdict intake; runtime trust policy/scoring remain disabled."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import JSON, DateTime, ForeignKey, String, delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.runtime_trust import (
    RUNTIME_CONTEXT,
    RuntimeAttestation,
    RuntimeDecision,
    check_binding,
    decide,
)
from reverse_hr.contracts.suite_validation import build_plan
from reverse_hr.contracts.suite_verdict import VERDICT_CONTEXT, SuiteVerdict
from reverse_hr.contracts.test_suites import SuiteDefinition, digest
from reverse_hr.protocols.verdict_delivery import (
    INTAKE_REQUEST,
    INTAKE_RESPONSE,
    MAX_BYTES,
    VerdictDelivery,
    VerdictReceipt,
)
from reverse_hr.services.assessment.domain.assessment import AssessmentBase, ContentRevision
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_sessions import subject_lock
from reverse_hr.services.assessment.domain.assessment_tests import TestSuite, view
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.db import enqueue
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, fresh, sign, verify


class ValidationIntake(AssessmentBase):
    __tablename__ = "suite_validation_intakes"
    validation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    suite_id: Mapped[str] = mapped_column(ForeignKey("test_suites.suite_id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    proof: Mapped[dict] = mapped_column(JSON)
    proof_signature: Mapped[str] = mapped_column(String(128))
    attestation: Mapped[dict | None] = mapped_column(JSON)
    attestation_signature: Mapped[str | None] = mapped_column(String(128))
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IntakeView(Contract):
    validation_id: UUID
    suite_id: UUID
    verdict: Literal["accepted", "rejected"]
    proof: SuiteVerdict
    received_at: datetime
    signature_verified: Literal[True] = True
    runtime_validated: Literal[False] = False
    scoring_enabled: Literal[False] = False


router = APIRouter(tags=["assessment-validation-verdicts"])


def current_suite(session, owner, proof):
    suite = session.scalar(
        select(TestSuite).where(TestSuite.suite_id == str(proof.pin.suite_id)).with_for_update()
    )
    if (
        suite is None
        or suite.status != "reviewed"
        or suite.created_by != str(owner)
        or suite.revision_id != str(proof.pin.revision_id)
        or suite.definition_digest != proof.pin.definition_digest
        or suite.content_digest != proof.pin.content_digest
    ):
        return False
    revision = session.scalar(
        select(ContentRevision)
        .where(ContentRevision.revision_id == suite.revision_id)
        .with_for_update()
    )
    if revision is None or revision.status != "published":
        return False
    created = (
        suite.created_at.replace(tzinfo=UTC)
        if suite.created_at.tzinfo is None
        else suite.created_at
    )
    published = revision.published_at
    if published is None:
        return False
    published = published.replace(tzinfo=UTC) if published.tzinfo is None else published
    if proof.completed_at < max(created, published):
        return False
    try:
        view(session, suite.suite_id)
        plan = build_plan(
            SuiteDefinition.model_validate(suite.definition), proof.pin, proof.validation_id
        )
    except (ValueError, HTTPException) as exc:
        raise HTTPException(503) from exc
    return digest(plan) == proof.plan_digest and len(plan.inputs) == proof.captures_count


@router.post("/internal/v1/suite-validation-verdict", response_model=VerdictReceipt)
def receive(
    request: Request,
    body: VerdictDelivery,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    proof = body.proof
    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(request.app.state, "assessment_signatures", None)
        if signatures is None:
            signatures = Signatures.from_settings(request.app.state.settings)
            request.app.state.assessment_signatures = signatures
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, "code-runner", signature, INTAKE_REQUEST, body)
        verify(signatures, "code-runner", body.proof_signature, VERDICT_CONTEXT, proof)
        if body.attestation is not None:
            verify(
                signatures,
                "code-runner",
                body.attestation_signature,
                RUNTIME_CONTEXT,
                body.attestation,
            )
            check_binding(proof, body.attestation)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    if proof.completed_at.tzinfo is None or proof.completed_at > now + timedelta(minutes=2):
        raise HTTPException(401)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(MaterialNonce).where(MaterialNonce.expires_at < now))
            session.add(
                MaterialNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60))
            )
            session.flush()
            subject = subject_lock(session, proof.owner_id, allow_blocked=True)
            allowed = not subject.blocked
            if allowed:
                try:
                    request.app.state.processing_access.check(proof.owner_id)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            allowed = allowed and current_suite(session, proof.owner_id, proof)
            if allowed:
                row = session.get(ValidationIntake, str(proof.validation_id))
                data = proof.model_dump(mode="json")
                report = body.attestation.model_dump(mode="json") if body.attestation else None
                if row is not None:
                    if (
                        row.proof != data
                        or row.proof_signature != body.proof_signature
                        or row.owner_id != str(proof.owner_id)
                        or row.suite_id != str(proof.pin.suite_id)
                    ):
                        raise HTTPException(409)
                    if report is not None:
                        if row.attestation is None:
                            row.attestation = report
                            row.attestation_signature = body.attestation_signature
                            enqueue(
                                session,
                                EventEnvelope(
                                    event_type="assessment.runtime_attestation_received.v1",
                                    producer="assessment",
                                    aggregate_id=proof.validation_id,
                                    aggregate_version=2,
                                    correlation_id=proof.validation_id,
                                    payload={
                                        "candidate_id": proof.owner_id,
                                        "validation_id": proof.validation_id,
                                        "suite_id": proof.pin.suite_id,
                                    },
                                ),
                            )
                        elif {k: v for k, v in row.attestation.items() if k != "issued_at"} != {
                            k: v for k, v in report.items() if k != "issued_at"
                        }:
                            raise HTTPException(409)
                else:
                    session.add(
                        ValidationIntake(
                            validation_id=str(proof.validation_id),
                            suite_id=str(proof.pin.suite_id),
                            owner_id=str(proof.owner_id),
                            proof=data,
                            proof_signature=body.proof_signature,
                            attestation=report,
                            attestation_signature=body.attestation_signature,
                            received_at=now,
                        )
                    )
                    enqueue(
                        session,
                        EventEnvelope(
                            event_type="assessment.validation_verdict_received.v1",
                            producer="assessment",
                            aggregate_id=proof.validation_id,
                            aggregate_version=1,
                            correlation_id=proof.validation_id,
                            payload={
                                "candidate_id": proof.owner_id,
                                "validation_id": proof.validation_id,
                                "suite_id": proof.pin.suite_id,
                            },
                        ),
                    )
            receipt = VerdictReceipt(
                candidate_id=proof.owner_id,
                requester=body.requester,
                purpose=body.purpose,
                nonce=body.nonce,
                issued_at=datetime.now(UTC),
                validation_id=proof.validation_id,
                proof_digest=digest(proof),
                attestation_digest=digest(body.attestation) if body.attestation else None,
                allowed=allowed,
                verdict=proof.verdict if allowed else None,
            )
            raw = canonical(receipt)
            if len(raw) > MAX_BYTES:
                raise HTTPException(503)
            try:
                signed = sign(signatures, INTAKE_RESPONSE, receipt)
            except Exception as exc:
                raise HTTPException(503) from exc
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc


@router.get("/v1/test-suites/{suite_id}/validations/{validation_id}", response_model=IntakeView)
def get(request: Request, actor: Actor, suite_id: UUID, validation_id: UUID):
    actor.require("content_admin", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        row, proof, _ = history(request, session, actor, suite_id, validation_id)
        received = (
            row.received_at.replace(tzinfo=UTC)
            if row.received_at.tzinfo is None
            else row.received_at
        )
        return IntakeView(
            validation_id=validation_id,
            suite_id=suite_id,
            verdict=proof.verdict,
            proof=proof,
            received_at=received,
        )


def history(request, session, actor, suite_id, validation_id):
    row = session.get(ValidationIntake, str(validation_id))
    if row is None or row.suite_id != str(suite_id):
        raise HTTPException(404)
    for subject in sorted({str(actor.subject), row.owner_id}):
        subject_lock(session, subject)
        request.app.state.processing_access.check(UUID(subject))
    proof, report = verified_intake(request, row)
    return row, proof, report


def verified_intake(request, row):
    try:
        signatures = getattr(
            request.app.state, "assessment_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        proof = SuiteVerdict.model_validate(row.proof)
        verify(signatures, "code-runner", row.proof_signature, VERDICT_CONTEXT, proof)
        if (
            str(proof.validation_id) != row.validation_id
            or str(proof.pin.suite_id) != row.suite_id
            or str(proof.owner_id) != row.owner_id
        ):
            raise ValueError("Corrupted intake binding")
        report = None
        if (row.attestation is None) != (row.attestation_signature is None):
            raise ValueError("Incomplete attestation")
        if row.attestation is not None:
            report = RuntimeAttestation.model_validate(row.attestation)
            verify(signatures, "code-runner", row.attestation_signature, RUNTIME_CONTEXT, report)
            check_binding(proof, report)
    except Exception as exc:
        raise HTTPException(409) from exc
    return proof, report


@router.get(
    "/v1/test-suites/{suite_id}/validations/{validation_id}/runtime-admission",
    response_model=RuntimeDecision,
)
def runtime_admission(request: Request, actor: Actor, suite_id: UUID, validation_id: UUID):
    actor.require("content_admin", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        _, proof, report = history(request, session, actor, suite_id, validation_id)
        return decide(
            proof,
            report,
            request.app.state.settings.assessment_trusted_runtimes,
            active=current_suite(session, proof.owner_id, proof),
        )
