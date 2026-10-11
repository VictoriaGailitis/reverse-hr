"""Signed access to a generated suite plan; sensitive code stays off the broker."""

from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, Header, HTTPException, Request, Response
from pydantic import model_validator
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reverse_hr.contracts.suite_pin import SuitePin
from reverse_hr.contracts.suite_validation import ValidationPlan, build_plan
from reverse_hr.contracts.test_suites import SuiteDefinition
from reverse_hr.protocols.evaluation_artifact_access import bound
from reverse_hr.protocols.processing_access import ProcessingAccess, ProcessingRequest
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, fresh, sign, verify

REQUEST = b"reverse-hr.generated-validation-request.v1\0"
RESPONSE = b"reverse-hr.generated-validation-response.v1\0"


class GeneratedValidationRequest(ProcessingRequest):
    requester: Literal["code-runner"] = "code-runner"
    purpose: Literal["generated-validation"] = "generated-validation"
    generation_id: UUID


class GeneratedValidationReceipt(GeneratedValidationRequest):
    allowed: bool
    plan: ValidationPlan | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.allowed != (self.plan is not None):
            raise ValueError("Generated validation admission and plan must agree")
        if self.plan and (self.plan.validation_id is None):
            raise ValueError("Validation identifier required")
        return self


class GeneratedValidationAccess(ProcessingAccess):
    def fetch(self, owner, generation_id):
        body = GeneratedValidationRequest(
            candidate_id=owner,
            generation_id=generation_id,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signature = self._send(
                "generated-validation",
                canonical(body),
                sign(self.signatures, REQUEST, body),
                origin=self.settings.assessment_api_url,
                max_bytes=2097152,
            )
            receipt = GeneratedValidationReceipt.model_validate_json(raw)
            verify(self.signatures, "assessment", signature, RESPONSE, receipt)
            if (
                len(raw) > 2097152
                or raw != canonical(receipt)
                or not bound(body, receipt)
                or receipt.allowed != (receipt.plan is not None)
            ):
                raise ValueError("Invalid generated plan receipt")
        except Exception as exc:
            raise HTTPException(503) from exc
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt.plan


router = APIRouter(prefix="/internal/v1", tags=["generated-validation"])


@router.post("/generated-validation")
def generated_validation(
    request: Request,
    body: GeneratedValidationRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
    from reverse_hr.services.assessment.domain.assessment_generation import (
        GenerationJob,
        GenerationReference,
    )
    from reverse_hr.services.assessment.domain.assessment_sessions import subject_lock
    from reverse_hr.services.assessment.domain.assessment_tests import TestSuite

    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    signatures = getattr(
        request.app.state, "assessment_signatures", None
    ) or Signatures.from_settings(request.app.state.settings)
    try:
        verify(signatures, "code-runner", signature, REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    try:
        with Session(request.app.state.engine) as session, session.begin():
            now = datetime.now(UTC)
            session.execute(delete(MaterialNonce).where(MaterialNonce.expires_at < now))
            session.add(MaterialNonce(nonce=str(body.nonce), expires_at=now + timedelta(minutes=1)))
            session.flush()
            subject = subject_lock(session, body.candidate_id, allow_blocked=True)
            job = session.get(GenerationJob, str(body.generation_id))
            ref = session.get(GenerationReference, job.version_id) if job else None
            suite = session.get(TestSuite, job.suite_id) if job and job.suite_id else None
            allowed = bool(
                not subject.blocked
                and job
                and job.author_id == str(body.candidate_id)
                and job.status == "validating"
                and job.runtime_fingerprint
                and ref
                and ref.status != "retired"
                and suite
                and suite.status == "reviewed"
            )
            plan = None
            if allowed:
                request.app.state.processing_access.check(body.candidate_id)
                request.app.state.processing_access.check(UUID(ref.author_id))
                if ref.approved_by:
                    request.app.state.processing_access.check(UUID(ref.approved_by))
                if ref.organization_id:
                    from reverse_hr.services.assessment.generation_worker import check_owners

                    check_owners(request, session, ref, job.author_id)
                plan = build_plan(
                    SuiteDefinition.model_validate(suite.definition),
                    SuitePin(
                        suite_id=suite.suite_id,
                        revision_id=suite.revision_id,
                        content_digest=suite.content_digest,
                        definition_digest=suite.definition_digest,
                        runtime_fingerprint=job.runtime_fingerprint,
                    ),
                    UUID(job.validation_id),
                )
            receipt = GeneratedValidationReceipt(
                **(body.model_dump() | {"issued_at": now}), allowed=allowed, plan=plan
            )
            return Response(
                content=canonical(receipt),
                media_type="application/json",
                headers={"X-HR-Signature": sign(signatures, RESPONSE, receipt)},
            )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
