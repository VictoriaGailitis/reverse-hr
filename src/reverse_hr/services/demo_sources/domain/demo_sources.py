"""Synthetic FSP/Hackathon Platform adapters, not a real provider API."""

from uuid import NAMESPACE_URL, uuid5

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy.orm import DeclarativeBase

from reverse_hr.protocols.exchange import ExchangeReceipt, ExchangeRequest, respond
from reverse_hr.protocols.market_access import Signature
from reverse_hr.protocols.market_state import NonceColumns


class DemoSourceBase(DeclarativeBase):
    pass


class DemoSourceNonce(NonceColumns, DemoSourceBase):
    __tablename__ = "demo_source_nonces"


router = APIRouter(prefix="/internal/v1/exchange", tags=["synthetic-demo-source"])


def external_record_id(provider, candidate_id):
    # Keep synthetic record IDs stable across the adapter rename to prevent duplicate imports.
    namespace = "demo-codenrock" if provider == "demo-hackathon-platform" else provider
    return str(uuid5(NAMESPACE_URL, namespace + ":" + str(candidate_id)))


@router.post("/pull", response_model=ExchangeReceipt)
def pull(request: Request, body: ExchangeRequest, signature: Signature = None):
    if body.operation != "pull" or request.app.state.settings.deployment_mode != "demo":
        raise HTTPException(409)

    def handle(session):
        if body.payload != {"external_account": str(body.candidate_id)}:
            raise HTTPException(409, "Demo binding must be issued for the authenticated candidate")
        scenario = request.app.state.settings.demo_source_scenario
        if scenario == "unavailable":
            raise HTTPException(503)
        provider = request.app.state.settings.service_name
        records = (
            []
            if scenario == "empty"
            else [
                dict(
                    external_id=external_record_id(provider, body.candidate_id),
                    external_account=str(body.candidate_id),
                    external_version=2 if scenario in {"updated", "revoked"} else 1,
                    event="Synthetic " + provider + " demonstration",
                    discipline="Programming",
                    occurred_on="2026-01-01",
                    specialization="backend",
                    format="individual",
                    place=1,
                    group_size=10,
                    points=100 if scenario == "updated" else 80,
                    evidence_url=None,
                    revoked=scenario == "revoked",
                )
            ]
        )
        return {"records": records, "demo": True}

    return respond(request, body, signature, DemoSourceNonce, {"integration"}, handle)
