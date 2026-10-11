from sqlalchemy import text
from sqlalchemy.orm import Session

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.services.privacy.backup_archive import configure as configure_backups

    configure_backups(engine, config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    from reverse_hr.services.privacy.domain.privacy_market import router as market_router

    app.include_router(market_router)
    from reverse_hr.services.privacy.domain.privacy_company_results import (
        router as company_results_router,
    )

    app.include_router(company_results_router)
    from reverse_hr.services.privacy.domain.privacy_requests import (
        router as subject_requests_router,
    )

    app.include_router(subject_requests_router)
    from reverse_hr.services.privacy.domain.privacy_archives import router as archives_router

    app.include_router(archives_router)
    domain_name = "privacy".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    connection.execute(text("SELECT 1 FROM company_result_grants LIMIT 0"))
    connection.execute(text("SELECT 1 FROM privacy_subject_requests LIMIT 0"))
    connection.execute(text("SELECT 1 FROM privacy_request_history LIMIT 0"))
    connection.execute(text("SELECT 1 FROM privacy_archives LIMIT 0"))
    connection.execute(text("SELECT 1 FROM privacy_archive_pages LIMIT 0"))
    connection.execute(text("SELECT 1 FROM backup_store_identity LIMIT 0"))
    from reverse_hr.services.privacy.backup_archive import bind as backup_bind

    with Session(engine) as session, session.begin():
        backup_bind(session)
    table = {
        "candidate": "candidate_profiles",
        "privacy": "consents",
        "employer": "organizations",
        "assessment": "content_revisions",
        "coding-workspace": "workspaces",
        "code-runner": "runner_jobs",
        "evaluation": "evaluation_intakes",
    }["privacy"]
    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    restriction_table = {
        "candidate": "candidate_subjects",
        "employer": "employer_subjects",
        "privacy": "processing_nonces",
        "assessment": "assessment_subjects",
        "coding-workspace": "workspace_subjects",
        "code-runner": "runner_subjects",
        "evaluation": "evaluation_subjects",
    }["privacy"]
    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="privacy")
    if config.service_name != "privacy":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
