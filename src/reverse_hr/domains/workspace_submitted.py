"""Immutable source export for hidden tests with live Assessment permission."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.domains.coding_workspace import FilesCommand, Snapshot, Workspace, subject_lock
from reverse_hr.domains.workspace_evaluation import ArtifactNonce
from reverse_hr.event_transport import Signatures
from reverse_hr.processing_access import canonical, fresh, sign, verify
from reverse_hr.submitted_access import (
    MAX_BYTES,
    SOURCE_REQUEST,
    SOURCE_RESPONSE,
    SubmittedSourceReceipt,
    SubmittedSourceRequest,
)

router = APIRouter(prefix="/internal/v1", tags=["internal-submitted-tests"])


def matches(session, body):
    workspace = session.get(Workspace, str(body.workspace_id))
    snapshot = session.get(Snapshot, str(body.snapshot_id))
    if (
        workspace
        and snapshot
        and workspace.candidate_id == str(body.candidate_id)
        and workspace.session_id == str(body.session_id)
        and workspace.stage_id == str(body.stage_id)
        and snapshot.workspace_id == workspace.workspace_id
        and snapshot.version == body.snapshot_version
        and snapshot.digest == body.snapshot_digest
    ):
        return snapshot
    return None


@router.post("/submitted-tests-source", response_model=SubmittedSourceReceipt)
def submitted_source(
    request: Request,
    body: SubmittedSourceRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "workspace_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, body.requester, signature, SOURCE_REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    refs = {
        k: getattr(body, k)
        for k in (
            "candidate_id",
            "session_id",
            "stage_id",
            "workspace_id",
            "snapshot_id",
            "node_id",
            "runtime_fingerprint",
        )
    }
    try:
        with Session(request.app.state.engine) as session:
            exists = matches(session, body) is not None
        material = None
        if exists:
            try:
                material = request.app.state.submitted_access.fetch(**refs)
            except HTTPException as exc:
                if exc.status_code != 409:
                    raise
        now = datetime.now(UTC)
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(ArtifactNonce).where(ArtifactNonce.expires_at < now))
            session.add(
                ArtifactNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60))
            )
            session.flush()
            subject = subject_lock(session, body.candidate_id, allow_blocked=True)
            snapshot = matches(session, body)
            allowed = bool(
                not subject.blocked
                and snapshot
                and material
                and material.binding == body.binding
                and material.snapshot_version == body.snapshot_version
                and material.snapshot_digest == body.snapshot_digest
            )
            if allowed:
                try:
                    request.app.state.processing_access.check(body.candidate_id)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            receipt = SubmittedSourceReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=allowed,
                manifest=FilesCommand(files=snapshot.files) if allowed else None,
            )
            raw = canonical(receipt)
            if len(raw) > MAX_BYTES:
                raise HTTPException(503)
            signed = sign(signatures, SOURCE_RESPONSE, receipt)
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
