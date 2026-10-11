"""Assessment's metadata-only artifact receipt, without recursive stage admission."""

from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import DateTime, String, delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.protocols.snapshot_access import (
    SNAPSHOT_REQUEST,
    SNAPSHOT_RESPONSE,
    SnapshotReceipt,
    SnapshotRequest,
)
from reverse_hr.services.coding_workspace.domain.coding_workspace import (
    Snapshot,
    Workspace,
    WorkspaceBase,
    subject_lock,
)
from reverse_hr.shared.signing import canonical, fresh, sign, verify


class SnapshotNonce(WorkspaceBase):
    __tablename__ = "snapshot_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


router = APIRouter(prefix="/internal/v1", tags=["internal-assessment"])


@router.post("/snapshot-receipt", response_model=SnapshotReceipt)
def snapshot_receipt(
    request: Request,
    body: SnapshotRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.shared.event_transport import Signatures

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
        verify(signatures, body.requester, signature, SNAPSHOT_REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(SnapshotNonce).where(SnapshotNonce.expires_at < now))
            session.add(
                SnapshotNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60))
            )
            session.flush()
            subject = subject_lock(session, body.candidate_id, allow_blocked=True)
            workspace = session.get(Workspace, str(body.workspace_id))
            snapshot = session.get(Snapshot, str(body.snapshot_id))
            allowed = bool(
                not subject.blocked
                and workspace
                and snapshot
                and workspace.candidate_id == str(body.candidate_id)
                and workspace.session_id == str(body.session_id)
                and workspace.stage_id == str(body.stage_id)
                and snapshot.workspace_id == workspace.workspace_id
            )
            if allowed:
                try:
                    request.app.state.processing_access.check(body.candidate_id)
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            values = (
                {
                    "format": workspace.format,
                    "snapshot_version": snapshot.version,
                    "digest": snapshot.digest,
                }
                if allowed
                else {}
            )
            receipt = SnapshotReceipt(
                **(body.model_dump() | {"issued_at": now}), allowed=allowed, **values
            )
            signed = sign(signatures, SNAPSHOT_RESPONSE, receipt)
        return Response(
            content=canonical(receipt),
            media_type="application/json",
            headers={"X-HR-Signature": signed},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
