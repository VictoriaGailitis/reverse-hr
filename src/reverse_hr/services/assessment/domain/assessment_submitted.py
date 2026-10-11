"""Submitted-test permission is distinct from Workspace write and Evaluation read."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.contracts.session_test_pins import stored_pins
from reverse_hr.protocols.submitted_access import (
    MAX_BYTES,
    REQUEST,
    RESPONSE,
    SubmittedMaterial,
    SubmittedReceipt,
    SubmittedRequest,
)
from reverse_hr.services.assessment.domain.assessment_evaluation import MaterialNonce
from reverse_hr.services.assessment.domain.assessment_plan_tests import check_pins, owner_ids
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PracticalSession,
    StageState,
    subject_lock,
)
from reverse_hr.services.assessment.domain.assessment_tests import TestSuite
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, fresh, sign, verify

router = APIRouter(prefix="/internal/v1", tags=["internal-submitted-tests"])


@router.post("/submitted-tests", response_model=SubmittedReceipt)
def submitted_tests(
    request: Request,
    body: SubmittedRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "assessment_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, body.requester, signature, REQUEST, body)
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
            row = session.get(PracticalSession, str(body.session_id))
            stage = session.get(StageState, str(body.stage_id))
            material = None
            if (
                row
                and stage
                and row.candidate_id == str(body.candidate_id)
                and row.status in {"in_progress", "submitted"}
                and stage.session_id == row.session_id
                and stage.status == "submitted"
                and stage.version == 3
                and stage.workspace_id == str(body.workspace_id)
                and stage.snapshot_id == str(body.snapshot_id)
            ):
                try:
                    pins = stored_pins(row, for_session=True)
                    owners = owner_ids(session, body.candidate_id, pins)
                    for owner in sorted(owners):
                        subject_lock(session, owner)
                        if owner != str(body.candidate_id):
                            request.app.state.processing_access.check(UUID(owner))
                    request.app.state.processing_access.check_assessment(
                        body.candidate_id, UUID(row.consent_id)
                    )
                    check_pins(request, session, pins, row.stages, current=True)
                    binding = next((p for p in pins if p.stage_id == body.stage_id), None)
                    if (
                        binding
                        and binding.node_id == body.node_id
                        and binding.pin.runtime_fingerprint == body.runtime_fingerprint
                    ):
                        suite = session.get(TestSuite, str(binding.pin.suite_id))
                        material = SubmittedMaterial(
                            consent_id=row.consent_id,
                            snapshot_version=stage.snapshot_version,
                            snapshot_digest=stage.digest,
                            binding=binding,
                            definition=suite.definition,
                        )
                except ValueError as exc:
                    raise HTTPException(409, "Corrupted submitted pins") from exc
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
            receipt = SubmittedReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=material is not None,
                material=material,
            )
            raw = canonical(receipt)
            if len(raw) > MAX_BYTES:
                raise HTTPException(503)
            signed = sign(signatures, RESPONSE, receipt)
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
