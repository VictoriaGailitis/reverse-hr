from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    # Register service-owned route extensions before including the base router.
    domain_module("hiring_communication_risk")
    domain_module("hiring_dialogs")
    domain_module("hiring_moderation")
    domain_module("hiring_trust")
    domain_module("hiring_vacancies")

    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.exchange import ExchangeAccess
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.exchange_access = ExchangeAccess(config)
    app.state.market_access = MarketAccess(config)
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.market_access = MarketAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    from reverse_hr.services.hiring.domain import hiring_vacancies
    from reverse_hr.services.hiring.domain.hiring import internal_router as market_router

    app.include_router(market_router)
    app.include_router(hiring_vacancies.router)
    domain_name = "hiring".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    from reverse_hr.coordination import review_sla

    app.include_router(review_sla.make_router("hiring"))
    from reverse_hr.services.hiring.domain.hiring_ats import router as ats_router

    app.include_router(ats_router)


def check_ready(app, config, engine, connection):
    connection.execute(text("SELECT 1 FROM hiring_ats_statuses LIMIT 0"))
    connection.execute(text("SELECT 1 FROM hiring_employer_reviews LIMIT 0"))
    connection.execute(text("SELECT 1 FROM hiring_moderation_appeals LIMIT 0"))
    connection.execute(text("SELECT 1 FROM hiring_invitation_revisions LIMIT 0"))
    for suffix in ("review_pool", "review_sla", "review_actions"):
        connection.execute(text(f"SELECT 1 FROM {'hiring'}_{suffix} LIMIT 0"))
    connection.execute(text("SELECT 1 FROM hiring_communication_risks LIMIT 0"))
    names = (
        "hiring_needs",
        "hiring_invitations",
        "hiring_subjects",
        "hiring_market_nonces",
        "hiring_dialogs",
        "hiring_messages",
        "hiring_employer_blocks",
        "hiring_complaints",
        "hiring_complaint_cases",
        "hiring_complaint_decisions",
        "hiring_notices",
        "hiring_vacancies",
        "hiring_vacancy_decisions",
        "hiring_applications",
        "hiring_application_changes",
    )
    for name in names:
        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="hiring")
    if config.service_name != "hiring":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
