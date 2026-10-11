from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    # Register service-owned route extensions before including the base router.
    domain_module("candidate_grades")
    domain_module("candidate_preferences")
    domain_module("candidate_resume")
    from reverse_hr.services.candidate.domain.candidate_recommendations import internal_router

    app.include_router(internal_router)

    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.exchange import ExchangeAccess
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.exchange_access = ExchangeAccess(config)
    app.state.market_access = MarketAccess(config)
    from reverse_hr.protocols.resume_access import PDFGuest
    from reverse_hr.services.candidate.domain import candidate_resume
    from reverse_hr.shared.media_antivirus import ClamdScanner

    candidate_resume.configure(engine, config)
    app.state.resume_guest = PDFGuest(config)
    app.state.resume_scanner = ClamdScanner(config) if config.resume_antivirus_required else None
    app.include_router(candidate_resume.router)
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.market_access = MarketAccess(config)
    from reverse_hr.services.candidate.domain.candidate_market import (
        internal_router as market_router,
    )

    app.include_router(market_router)
    from reverse_hr.protocols.qualification_policy_access import QualificationPolicyAccess

    app.state.qualification_policy_access = QualificationPolicyAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "candidate".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    connection.execute(text("SELECT version FROM candidate_contacts LIMIT 0"))
    connection.execute(text("SELECT 1 FROM candidate_preferences LIMIT 0"))
    connection.execute(text("SELECT 1 FROM candidate_task_subscriptions LIMIT 0"))
    connection.execute(text("SELECT 1 FROM candidate_task_recommendations LIMIT 0"))
    table = {
        "candidate": "candidate_profiles",
        "privacy": "consents",
        "employer": "organizations",
        "assessment": "content_revisions",
        "coding-workspace": "workspaces",
        "code-runner": "runner_jobs",
        "evaluation": "evaluation_intakes",
    }["candidate"]
    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    restriction_table = {
        "candidate": "candidate_subjects",
        "employer": "employer_subjects",
        "privacy": "processing_nonces",
        "assessment": "assessment_subjects",
        "coding-workspace": "workspace_subjects",
        "code-runner": "runner_subjects",
        "evaluation": "evaluation_subjects",
    }["candidate"]
    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))
    connection.execute(text("SELECT 1 FROM candidate_grade_history LIMIT 0"))
    for name in (
        "candidate_publication",
        "candidate_contacts",
        "candidate_market_nonces",
        "candidate_resume_imports",
        "candidate_resumes",
        "candidate_resume_store",
    ):
        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))
    if "candidate" == "candidate" and config.resume_storage_root:
        try:
            from reverse_hr.services.candidate.domain.candidate_resume import storage

            with Session(engine) as session, session.begin():
                storage(session)
            app.state.resume_guest.ready()
            if config.resume_antivirus_required:
                app.state.resume_scanner.ready()
        except Exception as exc:
            raise HTTPException(503) from exc


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="candidate")
    if config.service_name != "candidate":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
