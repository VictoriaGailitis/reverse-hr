"""Fresh signed Candidate → Matching fetch of an explicit approved advice policy."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from reverse_hr.contracts import Contract
from reverse_hr.domains.matching import MatchingSubject
from reverse_hr.domains.matching_governance import PolicyNonce, RankingPolicy, load_policy
from reverse_hr.market_access import Signature
from reverse_hr.market_state import lock
from reverse_hr.processing_access import ProcessingAccess, canonical, fresh, sign, verify

REQUEST_CONTEXT = b"reverse-hr.qualification-policy.request.v1\0"
RESPONSE_CONTEXT = b"reverse-hr.qualification-policy.response.v1\0"
MAX_BYTES = 8192
router = APIRouter()


class PolicyRequest(Contract):
    requester: Literal["candidate"] = "candidate"
    candidate_id: UUID
    nonce: UUID
    issued_at: datetime
    policy_id: UUID
    mode: Literal["demo", "production"]


class PolicyReceipt(PolicyRequest):
    policy: RankingPolicy


class QualificationPolicyAccess(ProcessingAccess):
    def fetch(self, policy_id, candidate_id, mode="demo"):
        body = PolicyRequest(
            policy_id=policy_id,
            candidate_id=candidate_id,
            mode=mode,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        try:
            raw, signed = self._send(
                "qualification-policy",
                canonical(body),
                sign(self.signatures, REQUEST_CONTEXT, body),
                origin=self.settings.matching_api_url,
                max_bytes=MAX_BYTES,
            )
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized policy")
            receipt = PolicyReceipt.model_validate_json(raw)
            verify(self.signatures, "matching", signed, RESPONSE_CONTEXT, receipt)
            if (
                raw != canonical(receipt)
                or not fresh(receipt.issued_at)
                or {k: v for k, v in receipt.model_dump().items() if k != "policy"}
                != body.model_dump()
            ):
                raise ValueError("Unbound policy")
            return receipt.policy
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503, "Approved qualification policy unavailable") from exc


@router.post("/internal/v1/qualification-policy")
async def policy_receipt(request: Request, signature: Signature = None):
    raw = await request.body()
    if len(raw) > MAX_BYTES or not signature:
        raise HTTPException(401)
    signatures = (
        getattr(request.app.state, "matching_signatures", None)
        or request.app.state.processing_access.signatures
    )
    try:
        body = PolicyRequest.model_validate_json(raw)
        verify(signatures, "candidate", signature, REQUEST_CONTEXT, body)
        if raw != canonical(body) or not fresh(body.issued_at):
            raise ValueError("Unbound policy request")
    except Exception as exc:
        raise HTTPException(401) from exc
    request.app.state.processing_access.check(body.candidate_id)
    policy, _ = load_policy(request, body.policy_id, body.mode)
    if request.app.state.settings.deployment_mode == "production" and body.mode == "demo":
        raise HTTPException(409, "Demo advice disabled in production")
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, MatchingSubject, body.candidate_id)
        session.execute(delete(PolicyNonce).where(PolicyNonce.expires_at < datetime.now(UTC)))
        session.add(
            PolicyNonce(
                nonce=str(body.nonce),
                expires_at=datetime.now(UTC) + timedelta(seconds=60),
            )
        )
        try:
            session.flush()
        except IntegrityError as exc:
            raise HTTPException(409, "Replayed policy request") from exc
        # Revalidate under the caller subject lock before disclosing a currently permitted policy.
        load_policy(request, body.policy_id, body.mode)
        receipt = PolicyReceipt(**body.model_dump(), policy=policy)
        return Response(
            canonical(receipt),
            media_type="application/json",
            headers={"X-HR-Signature": sign(signatures, RESPONSE_CONTEXT, receipt)},
        )
