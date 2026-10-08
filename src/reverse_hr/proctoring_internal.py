from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import Header, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.domains.proctoring import ProctorNonce, internal_router, stage_guard, summary
from reverse_hr.processing_access import canonical, fresh, sign, verify
from reverse_hr.proctoring_access import IntegrityReceipt, IntegrityRequest


@internal_router.post("/integrity-summary", response_model=IntegrityReceipt)
def integrity_receipt(
    request: Request,
    body: IntegrityRequest,
    signature: Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)] = None,
):
    from reverse_hr.event_transport import Signatures
    from reverse_hr.proctoring_access import REQUEST, RESPONSE, IntegrityReceipt

    if signature is None or not fresh(body.issued_at):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, "proctor_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, "evaluation", signature, REQUEST, body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(ProctorNonce).where(ProctorNonce.expires_at < now))
            session.add(ProctorNonce(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            stage_guard(request, session, body.candidate_id, body.session_id, body.stage_id)
            result = IntegrityReceipt(
                **(body.model_dump() | {"issued_at": now}),
                summary=summary(session, body.candidate_id, body.session_id, body.stage_id),
            )
            signed = sign(signatures, RESPONSE, result)
        return Response(
            canonical(result), media_type="application/json", headers={"X-HR-Signature": signed}
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
