from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    from reverse_hr.services.employer.domain.employer_market import router as market_router
    from reverse_hr.services.employer.domain.employer_trust import router as trust_router

    app.include_router(market_router)
    app.include_router(trust_router)
    domain_name = "employer".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    from reverse_hr.coordination import review_sla

    app.include_router(review_sla.make_router("employer"))


def check_ready(app, config, engine, connection):
    for table in ("employer_trust_decisions", "employer_sanctions", "employer_trust_appeals"):
        connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    for suffix in ("review_pool", "review_sla", "review_actions"):
        connection.execute(text(f"SELECT 1 FROM {'employer'}_{suffix} LIMIT 0"))
    table = {
        "candidate": "candidate_profiles",
        "privacy": "consents",
        "employer": "organizations",
        "assessment": "content_revisions",
        "coding-workspace": "workspaces",
        "code-runner": "runner_jobs",
        "evaluation": "evaluation_intakes",
    }["employer"]
    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    restriction_table = {
        "candidate": "candidate_subjects",
        "employer": "employer_subjects",
        "privacy": "processing_nonces",
        "assessment": "assessment_subjects",
        "coding-workspace": "workspace_subjects",
        "code-runner": "runner_subjects",
        "evaluation": "evaluation_subjects",
    }["employer"]
    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))
    connection.execute(text("SELECT 1 FROM ownership_recoveries LIMIT 0"))
    connection.execute(text("SELECT 1 FROM employer_market_nonces LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="employer")
    if config.service_name != "employer":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
