"""Signed reviewed-suite admission with replay protection; no scoring certificate."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.contracts.suite_validation import build_plan
from reverse_hr.contracts.test_suites import SuiteDefinition, digest
from reverse_hr.protocols.suite_admission import (
    MATERIAL_REQUEST,
    MATERIAL_RESPONSE,
    MAX_BYTES,
    MAX_MATERIAL_BYTES,
    SUITE_REQUEST,
    SUITE_RESPONSE,
    SuiteAdmissionRequest,
    SuiteMaterial,
    SuiteMaterialRequest,
    SuitePermit,
)
from reverse_hr.services.assessment.domain.assessment import ContentRevision
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_sessions import subject_lock
from reverse_hr.services.assessment.domain.assessment_tests import TestSuite, view
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, fresh, sign, verify

router = APIRouter(prefix="/internal/v1", tags=["internal-suite-validation"])


@router.post("/suite-validation-admission", response_model=SuitePermit)
def admit(
    request: Request,
    body: SuiteAdmissionRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    return respond(request, body, signature, export=False)


@router.post("/suite-validation-material", response_model=SuiteMaterial)
def material(
    request: Request,
    body: SuiteMaterialRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    return respond(request, body, signature, export=True)


def respond(request, body, signature, *, export):
    request_context = MATERIAL_REQUEST if export else SUITE_REQUEST
    response_context = MATERIAL_RESPONSE if export else SUITE_RESPONSE
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
        verify(signatures, "code-runner", signature, request_context, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(MaterialNonce).where(MaterialNonce.expires_at < now))
            session.add(
                MaterialNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60))
            )
            session.flush()
            subject = subject_lock(session, body.candidate_id, allow_blocked=True)
            suite = session.scalar(
                select(TestSuite)
                .where(TestSuite.suite_id == str(body.pin.suite_id))
                .with_for_update()
            )
            allowed = bool(
                not subject.blocked
                and suite
                and suite.status == "reviewed"
                and suite.created_by == str(body.candidate_id)
                and suite.revision_id == str(body.pin.revision_id)
                and suite.definition_digest == body.pin.definition_digest
                and suite.content_digest == body.pin.content_digest
            )
            if allowed:
                revision = session.scalar(
                    select(ContentRevision)
                    .where(ContentRevision.revision_id == suite.revision_id)
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
                allowed = bool(revision and revision.status == "published")
            if allowed:
                try:
                    request.app.state.processing_access.check(body.candidate_id)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            if allowed:
                # Revalidate private catalogue pins, then rebuild every input from
                # trusted content. A supplied fingerprint binds the permit only;
                # Runner's local probe must independently verify the runtime.
                try:
                    view(session, suite.suite_id)
                    definition = SuiteDefinition.model_validate(suite.definition)
                    plan = build_plan(definition, body.pin, body.validation_id)
                except (ValueError, HTTPException) as exc:
                    raise HTTPException(503) from exc
                allowed = digest(plan) == body.plan_digest
            args = body.model_dump() | {"issued_at": datetime.now(UTC), "allowed": allowed}
            receipt = (
                SuiteMaterial(**args, definition=definition if allowed else None)
                if export
                else SuitePermit(**args)
            )
            raw = canonical(receipt)
            if len(raw) > (MAX_MATERIAL_BYTES if export else MAX_BYTES):
                raise HTTPException(503)
            try:
                signed = sign(signatures, response_context, receipt)
            except Exception as exc:
                raise HTTPException(503) from exc
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
