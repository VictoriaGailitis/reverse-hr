"""Export immutable submitted source to Evaluation; no execution permission."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import DateTime, String, delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.domains.coding_workspace import (
    FilesCommand,
    Snapshot,
    Workspace,
    WorkspaceBase,
    subject_lock,
)
from reverse_hr.evaluation_artifact_access import (
    ARTIFACT_REQUEST,
    ARTIFACT_RESPONSE,
    MAX_ARTIFACT_BYTES,
    ArtifactReceipt,
    ArtifactRequest,
)
from reverse_hr.processing_access import canonical, fresh, sign, verify


class ArtifactNonce(WorkspaceBase):
    __tablename__ = "artifact_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


router = APIRouter(prefix="/internal/v1", tags=["internal-evaluation"])


def matches(session, body):
    workspace = session.get(Workspace, str(body.workspace_id))
    snapshot = session.get(Snapshot, str(body.snapshot_id))
    allowed = bool(
        workspace
        and snapshot
        and workspace.candidate_id == str(body.candidate_id)
        and workspace.session_id == str(body.session_id)
        and workspace.stage_id == str(body.stage_id)
        and workspace.format == body.format
        and snapshot.workspace_id == workspace.workspace_id
        and snapshot.version == body.snapshot_version
        and snapshot.digest == body.digest
    )
    return snapshot if allowed else None


@router.post("/evaluation-artifact", response_model=ArtifactReceipt)
def evaluation_artifact(
    request: Request,
    body: ArtifactRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.event_transport import Signatures

    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(request.app.state, "workspace_signatures", None)
        if signatures is None:
            signatures = Signatures.from_settings(request.app.state.settings)
            request.app.state.workspace_signatures = signatures
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, body.requester, signature, ARTIFACT_REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    try:
        # Assessment submission takes Assessment -> Workspace locks. Never invert that order.
        with Session(request.app.state.engine) as session:
            exists = matches(session, body) is not None
        permit = None
        if exists:
            try:
                permit = request.app.state.artifact_permit_access.check(body)
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
            allowed = bool(not subject.blocked and snapshot and permit)
            if allowed:
                if not fresh(permit.issued_at):
                    raise HTTPException(503)
                try:
                    request.app.state.processing_access.check(body.candidate_id)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            if allowed and not fresh(permit.issued_at):
                raise HTTPException(503)
            receipt = ArtifactReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=allowed,
                manifest=FilesCommand(files=snapshot.files) if allowed else None,
            )
            raw = canonical(receipt)
            if len(raw) > MAX_ARTIFACT_BYTES:
                raise HTTPException(503)
            signed = sign(signatures, ARTIFACT_RESPONSE, receipt)
        return Response(
            content=raw, media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
