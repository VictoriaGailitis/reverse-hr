from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.exchange import ExchangeAccess
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.exchange_access = ExchangeAccess(config)
    app.state.market_access = MarketAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "matching".replace("-", "_")
    domain = domain_module(domain_name)
    domain_module("matching_governance")
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    from reverse_hr.protocols.qualification_policy_access import (
        router as qualification_policy_router,
    )

    app.include_router(qualification_policy_router)
    app.state.matching_intent_gateway = None
    if config.matching_llm_enabled:
        from reverse_hr.services.matching.matching_gateway import MatchingIntentGateway

        app.state.matching_intent_gateway = MatchingIntentGateway(config)


def check_ready(app, config, engine, connection):
    names = (
        "matching_candidates",
        "matching_snapshots",
        "matching_subjects",
        "matching_governance_versions",
        "matching_intent_previews",
        "matching_policy_nonces",
    )
    for name in names:
        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="matching")
    if config.service_name != "matching":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
