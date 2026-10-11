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
    module = "demo-ats".replace("-", "_")
    domain = domain_module(module)
    app.include_router(domain.router)
    if hasattr(domain, "internal_router"):
        app.include_router(domain.internal_router)


def check_ready(app, config, engine, connection):
    module = "demo-ats".replace("-", "_")
    domain = domain_module(module)
    base = {
        "achievements": "AchievementsBase",
        "integration": "IntegrationBase",
        "demo-ats": "DemoATSBase",
        "demo-fsp": "DemoSourceBase",
        "demo-codenrock": "DemoSourceBase",
    }["demo-ats"]
    for table in getattr(domain, base).metadata.sorted_tables:
        connection.execute(text(f"SELECT 1 FROM {table.name} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="demo-ats")
    if config.service_name != "demo-ats":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
