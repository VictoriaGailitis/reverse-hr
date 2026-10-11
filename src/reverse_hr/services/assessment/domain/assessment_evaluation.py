"""Private pinned task/rubric export, bound to one submitted immutable artifact."""

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import DateTime, String, delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.session_test_pins import stored_pins
from reverse_hr.protocols.evaluation_access import (
    MATERIAL_REQUEST,
    MATERIAL_RESPONSE,
    MAX_MATERIAL_BYTES,
    MaterialReceipt,
    MaterialRequest,
    PinnedMaterial,
)
from reverse_hr.protocols.evaluation_artifact_access import (
    PERMIT_REQUEST,
    PERMIT_RESPONSE,
    ArtifactPermit,
    ArtifactPermitRequest,
)
from reverse_hr.services.assessment.domain.assessment import (
    AssessmentBase,
    ContentPackage,
    ContentRevision,
)
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PracticalSession,
    StageState,
    subject_lock,
)
from reverse_hr.shared.signing import canonical, fresh, sign, verify


class MaterialNonce(AssessmentBase):
    __tablename__ = "material_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


router = APIRouter(prefix="/internal/v1", tags=["internal-evaluation"])


@router.post("/evaluation-material", response_model=MaterialReceipt)
def evaluation_material(
    request: Request,
    body: MaterialRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.shared.event_transport import Signatures

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
        verify(signatures, body.requester, signature, MATERIAL_REQUEST, body)
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
            pins = []
            if row is not None and row.candidate_id == str(body.candidate_id):
                try:
                    pins = stored_pins(row, for_session=True)
                except ValueError as exc:
                    raise HTTPException(409, "Corrupted session pins") from exc
            from reverse_hr.services.assessment.domain.assessment_plan_tests import (
                check_pins,
                owner_ids,
            )

            owners = owner_ids(session, body.candidate_id, pins)
            blocked = False
            for owner in sorted(owners):
                blocked = subject_lock(session, owner, allow_blocked=True).blocked or blocked
            stage = session.get(StageState, str(body.stage_id))
            allowed = bool(
                not blocked
                and row
                and stage
                and row.candidate_id == str(body.candidate_id)
                and row.status in {"in_progress", "submitted", "completed"}
                and stage.session_id == row.session_id
                and stage.status == "submitted"
                and stage.version == 3
                and stage.workspace_id == str(body.workspace_id)
                and stage.snapshot_id == str(body.snapshot_id)
            )
            if allowed:
                try:
                    request.app.state.processing_access.check_assessment(
                        body.candidate_id, UUID(row.consent_id)
                    )
                    for owner in sorted(owners - {str(body.candidate_id)}):
                        request.app.state.processing_access.check(UUID(owner))
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            material = None
            if allowed:
                check_pins(request, session, pins, row.stages, current=False)
                spec = next(s for s in row.stages if s["stage_id"] == str(body.stage_id))
                if spec["format"] not in {"code", "sql"}:
                    artifact = request.app.state.practical_receipt_access.fetch(
                        body.candidate_id,
                        body.session_id,
                        body.stage_id,
                        body.workspace_id,
                        body.snapshot_id,
                        format=spec["format"],
                    )
                    if (
                        artifact.digest != stage.digest
                        or artifact.snapshot_version != stage.snapshot_version
                    ):
                        raise HTTPException(409)
                revision = session.get(ContentRevision, spec["revision_id"])
                # Retirement closes new admissions; existing sessions keep their immutable pins.
                if revision is None or revision.published_at is None:
                    raise HTTPException(503)
                package = ContentPackage.model_validate(revision.content)
                task = next(t for t in package.tasks if t.key == spec["task_key"])
                if (
                    task.format != spec["format"]
                    or task.instruction != spec["instruction"]
                    or task.duration_seconds != spec["duration_seconds"]
                ):
                    raise HTTPException(503)
                keys = {item.competency for item in task.rubric}
                binding = next((pin for pin in pins if pin.stage_id == body.stage_id), None)
                test_cases = []
                if binding:
                    from reverse_hr.contracts.test_suites import SuiteDefinition, digest
                    from reverse_hr.protocols.evaluation_access import TestCaseMetadata
                    from reverse_hr.services.assessment.domain.assessment_tests import TestSuite

                    suite = SuiteDefinition.model_validate(
                        session.get(TestSuite, str(binding.pin.suite_id)).definition
                    )
                    test_cases = [
                        TestCaseMetadata(
                            case_key=c.key, criterion_key=c.criterion_key, case_digest=digest(c)
                        )
                        for c in suite.cases
                    ]
                from sqlalchemy import select

                from reverse_hr.services.assessment.domain.company_assignments import (
                    CompanyAssignment,
                )

                assignment = session.scalar(
                    select(CompanyAssignment).where(CompanyAssignment.session_id == row.session_id)
                )
                material = PinnedMaterial(
                    company_organization_id=assignment.organization_id if assignment else None,
                    consent_id=row.consent_id,
                    plan_version_id=row.plan_version_id,
                    revision_id=revision.revision_id,
                    content_digest=hashlib.sha256(canonical(package)).hexdigest(),
                    task=task,
                    competencies=[c for c in package.competencies if c.key in keys],
                    snapshot_version=stage.snapshot_version,
                    snapshot_digest=stage.digest,
                    test_suite=binding,
                    test_cases=test_cases,
                )
            receipt = MaterialReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=allowed,
                material=material,
            )
            raw = canonical(receipt)
            if len(raw) > MAX_MATERIAL_BYTES:
                raise HTTPException(503)
            signed = sign(signatures, MATERIAL_RESPONSE, receipt)
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc


@router.post("/evaluation-artifact-admission", response_model=ArtifactPermit)
def artifact_admission(
    request: Request,
    body: ArtifactPermitRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.shared.event_transport import Signatures

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
        verify(signatures, body.requester, signature, PERMIT_REQUEST, body)
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
            row = session.get(PracticalSession, str(body.session_id))
            stage = session.get(StageState, str(body.stage_id))
            allowed = bool(
                not subject.blocked
                and body.format
                in {
                    "coding-workspace": {"code", "sql"},
                    "media": {"voice", "vcv"},
                    "whiteboard": {"whiteboard"},
                }[body.requester]
                and row
                and stage
                and row.candidate_id == str(body.candidate_id)
                and row.status in {"in_progress", "submitted", "completed"}
                and stage.session_id == row.session_id
                and stage.status == "submitted"
                and stage.version == 3
                and stage.workspace_id == str(body.workspace_id)
                and stage.snapshot_id == str(body.snapshot_id)
                and stage.snapshot_version == body.snapshot_version
                and stage.digest == body.digest
                and any(
                    s["stage_id"] == str(body.stage_id) and s["format"] == body.format
                    for s in row.stages
                )
            )
            if allowed:
                try:
                    request.app.state.processing_access.check_assessment(
                        body.candidate_id, UUID(row.consent_id)
                    )
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            status = ArtifactPermit(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}), allowed=allowed
            )
            signed = sign(signatures, PERMIT_RESPONSE, status)
        return Response(
            content=canonical(status),
            media_type="application/json",
            headers={"X-HR-Signature": signed},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
