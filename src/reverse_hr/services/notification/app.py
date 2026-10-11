from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.market_access = MarketAccess(config)
    from reverse_hr.services.notification.domain.notification_delivery import (
        internal_router as callback_router,
    )
    from reverse_hr.services.notification.domain.notification_delivery import (
        router as delivery_router,
    )

    app.include_router(delivery_router)
    app.include_router(callback_router)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "notification".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    connection.execute(
        text(
            "SELECT appeal_id, owner, category, assignment_id, application_id "
            "FROM notification_notices LIMIT 0"
        )
    )
    connection.execute(text("SELECT marketing_in_app FROM notification_preferences LIMIT 0"))
    for name in (
        "notification_subjects",
        "notification_notices",
        "notification_preferences",
        "notification_email_rate_windows",
        "notification_email_targets",
        "notification_email_preferences",
        "notification_email_challenges",
        "notification_deliveries",
        "notification_delivery_attempts",
        "notification_delivery_callbacks",
    ):
        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="notification")
    if config.service_name != "notification":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
