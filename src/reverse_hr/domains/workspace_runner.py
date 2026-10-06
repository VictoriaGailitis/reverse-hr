"""Signed immutable run manifests, admitted with current consent on every retrieval."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import DateTime, String, delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.domains.coding_workspace import (
    FilesCommand,
    RunRequest,
    Snapshot,
    Workspace,
    WorkspaceBase,
    subject_lock,
)
from reverse_hr.processing_access import canonical, fresh, sign, verify
from reverse_hr.runner_exchange import (
    MANIFEST_REQUEST,
    MANIFEST_RESPONSE,
    ManifestRequest,
    ManifestStatus,
)


class RunnerNonce(WorkspaceBase):
    __tablename__ = "runner_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


router = APIRouter(prefix="/internal/v1", tags=["internal-runner"])


@router.post("/run-manifest", response_model=ManifestStatus)
def run_manifest(
    request: Request,
    body: ManifestRequest,
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
        verify(signatures, body.requester, signature, MANIFEST_REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(RunnerNonce).where(RunnerNonce.expires_at < now))
            session.add(RunnerNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            subject = subject_lock(session, body.candidate_id, allow_blocked=True)
            row = session.get(Workspace, str(body.workspace_id))
            run = session.get(RunRequest, str(body.run_id))
            snapshot = session.get(Snapshot, str(body.snapshot_id))
            allowed = bool(
                not subject.blocked
                and row
                and row.candidate_id == str(body.candidate_id)
                and run
                and run.snapshot_id == str(body.snapshot_id)
                and snapshot
                and snapshot.workspace_id == row.workspace_id
            )
            if allowed:
                try:
                    request.app.state.processing_access.check(body.candidate_id)
                    kind = request.app.state.stage_access.check_stage(
                        body.candidate_id, UUID(row.session_id), UUID(row.stage_id), body.purpose
                    )
                    allowed = kind == row.format
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    allowed = False
            values = {}
            if allowed:
                values = {
                    "snapshot_version": snapshot.version,
                    "format": row.format,
                    "digest": snapshot.digest,
                    "manifest": FilesCommand(files=snapshot.files),
                }
            status = ManifestStatus(
                **(body.model_dump() | {"issued_at": now}), allowed=allowed, **values
            )
            response_signature = sign(signatures, MANIFEST_RESPONSE, status)
        return Response(
            content=canonical(status),
            media_type="application/json",
            headers={"X-HR-Signature": response_signature},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
