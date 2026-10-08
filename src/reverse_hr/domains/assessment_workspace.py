"""Internal stage admission; no candidate token or content is forwarded to Workspace."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Request, Response
from sqlalchemy import DateTime, String, delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.domains.assessment import AssessmentBase
from reverse_hr.domains.assessment_sessions import PracticalSession, StageState, subject_lock, utc
from reverse_hr.processing_access import canonical, fresh, sign, verify
from reverse_hr.stage_access import (
    STAGE_REQUEST_CONTEXT,
    STAGE_RESPONSE_CONTEXT,
    StageRequest,
    StageStatus,
)


class StageNonce(AssessmentBase):
    __tablename__ = "stage_nonces"
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


router = APIRouter(prefix="/internal/v1", tags=["internal-workspace"])


@router.post("/workspace-stage", response_model=StageStatus)
def workspace_stage(
    request: Request,
    body: StageRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.event_transport import Signatures

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
        verify(signatures, body.requester, signature, STAGE_REQUEST_CONTEXT, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(StageNonce).where(StageNonce.expires_at < now))
            session.add(StageNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            subject = subject_lock(session, body.candidate_id, allow_blocked=True)
            row = session.get(PracticalSession, str(body.session_id))
            stage = None
            if (
                not subject.blocked
                and row
                and row.candidate_id == str(body.candidate_id)
                and (
                    row.status in {"preflight", "in_progress", "submitted"}
                    or (body.requester == "proctoring" and body.purpose == "read")
                )
            ):
                stage = next(
                    (
                        s
                        for s in row.stages
                        if s["stage_id"] == str(body.stage_id)
                        and s["format"]
                        in {
                            "coding-workspace": {"code", "sql"},
                            "media": {"voice", "vcv"},
                            "whiteboard": {"whiteboard"},
                            "proctoring": {"code", "sql", "voice", "vcv", "whiteboard"},
                        }[body.requester]
                    ),
                    None,
                )
            if (
                stage
                and body.purpose == "write"
                and (row.status != "preflight" or body.requester != "coding-workspace")
            ):
                progress = session.get(StageState, str(body.stage_id))
                if (
                    row.status != "in_progress"
                    or row.current_stage_id != str(body.stage_id)
                    or progress is None
                    or progress.status != "active"
                    or now >= utc(progress.deadline)
                ):
                    stage = None
            if stage:
                try:
                    request.app.state.processing_access.check_assessment(
                        body.candidate_id, UUID(row.consent_id)
                    )
                except HTTPException as exc:
                    if exc.status_code != 409:
                        raise
                    stage = None
            status = StageStatus(
                **(body.model_dump() | {"issued_at": now}),
                allowed=stage is not None,
                format=stage["format"] if stage else None,
            )
            response_signature = sign(signatures, STAGE_RESPONSE_CONTEXT, status)
        return Response(
            content=canonical(status),
            media_type="application/json",
            headers={"X-HR-Signature": response_signature},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
