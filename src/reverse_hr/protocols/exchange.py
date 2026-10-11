"""Fixed-origin signed demo/partner exchange, fresh nonces and bound receipts."""

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.error import HTTPError
from uuid import UUID, uuid4

from fastapi import HTTPException, Request, Response
from pydantic import Field, ValidationError
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.test_suites import digest
from reverse_hr.protocols.market_access import Signature
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import canonical, fresh, sign, verify

MAX_BYTES = 262144
OWNERS = {"achievements", "integration", "demo-fsp", "demo-hackathon-platform", "demo-ats"}


class ExchangeRequest(Contract):
    requester: str = Field(min_length=1, max_length=40)
    operation: Literal[
        "outcome",
        "connection",
        "import",
        "summary",
        "resume",
        "pull",
        "push",
        "permission",
        "status",
        "erase",
    ]
    request_id: UUID
    candidate_id: UUID
    nonce: UUID
    issued_at: datetime
    payload: dict = Field(default_factory=dict)


class ExchangeReceipt(Contract):
    request_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    issued_at: datetime
    data: dict


def payload_digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def context(owner, operation, direction):
    return f"reverse-hr.exchange.{owner}.{operation}.{direction}.v1\0".encode()


class ExchangeAccess(ProcessingAccess):
    def call(self, owner, operation, candidate_id, request_id, **payload):
        if owner not in OWNERS:
            raise HTTPException(503)
        body = ExchangeRequest(
            requester=self.settings.service_name,
            operation=operation,
            candidate_id=candidate_id,
            request_id=request_id,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
            payload=payload,
        )
        raw = canonical(body)
        if len(raw) > MAX_BYTES:
            raise HTTPException(422)
        origin = getattr(self.settings, owner.replace("-", "_") + "_api_url")
        try:
            received, signed = self._send(
                "exchange/" + operation,
                raw,
                sign(self.signatures, context(owner, operation, "request"), body),
                origin=origin,
                max_bytes=MAX_BYTES,
            )
            if len(received) > MAX_BYTES:
                raise ValueError("Oversized exchange")
            receipt = ExchangeReceipt.model_validate_json(received)
            verify(self.signatures, owner, signed, context(owner, operation, "response"), receipt)
            if (
                received != canonical(receipt)
                or not fresh(receipt.issued_at)
                or receipt.request_digest != digest(body)
            ):
                raise ValueError("Unbound exchange")
            return receipt.data
        except HTTPError as exc:
            raise HTTPException(exc.code if exc.code in {401, 403, 404, 409, 422} else 503) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503) from exc


def respond(
    request: Request, body: ExchangeRequest, signature: Signature, nonce_model, callers, handler
):
    owner = request.app.state.settings.service_name
    if signature is None or body.requester not in callers or not fresh(body.issued_at):
        raise HTTPException(401)
    signatures = getattr(
        request.app.state, "exchange_signatures", None
    ) or Signatures.from_settings(request.app.state.settings)
    try:
        verify(
            signatures, body.requester, signature, context(owner, body.operation, "request"), body
        )
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(nonce_model).where(nonce_model.expires_at < now))
            session.add(nonce_model(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60)))
            session.flush()
            data = handler(session)
            receipt = ExchangeReceipt(
                request_digest=digest(body), issued_at=datetime.now(UTC), data=data
            )
            raw = canonical(receipt)
            if len(raw) > MAX_BYTES:
                raise HTTPException(503)
            signed = sign(signatures, context(owner, body.operation, "response"), receipt)
        return Response(
            raw,
            media_type="application/json",
            headers={"X-HR-Signature": signed, "Cache-Control": "no-store"},
        )
    except IntegrityError as exc:
        raise HTTPException(409) from exc
    except ValidationError as exc:
        raise HTTPException(422) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
