from sqlalchemy import text

from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.exchange import ExchangeAccess
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.exchange_access = ExchangeAccess(config)
    app.state.market_access = MarketAccess(config)
    module = "integration".replace("-", "_")
    domain = domain_module(module)
    app.include_router(domain.router)
    if hasattr(domain, "internal_router"):
        app.include_router(domain.internal_router)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)


def check_ready(app, config, engine, connection):
    module = "integration".replace("-", "_")
    domain = domain_module(module)
    base = {
        "achievements": "AchievementsBase",
        "integration": "IntegrationBase",
        "demo-ats": "DemoATSBase",
        "demo-fsp": "DemoSourceBase",
        "demo-codenrock": "DemoSourceBase",
    }["integration"]
    for table in getattr(domain, base).metadata.sorted_tables:
        connection.execute(text(f"SELECT 1 FROM {table.name} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="integration")
    if config.service_name != "integration":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
