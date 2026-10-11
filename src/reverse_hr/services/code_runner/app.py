from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.runner_exchange import ManifestAccess
    from reverse_hr.protocols.suite_admission import SuiteAdmissionAccess
    from reverse_hr.protocols.verdict_delivery import VerdictDeliveryAccess

    app.state.manifest_access = ManifestAccess(config)
    app.state.suite_admission = SuiteAdmissionAccess(config)
    app.state.verdict_delivery = VerdictDeliveryAccess(config)
    from reverse_hr.protocols.submitted_access import SubmittedAccess

    app.state.submitted_access = SubmittedAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "code-runner".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    table = {
        "candidate": "candidate_profiles",
        "privacy": "consents",
        "employer": "organizations",
        "assessment": "content_revisions",
        "coding-workspace": "workspaces",
        "code-runner": "runner_jobs",
        "evaluation": "evaluation_intakes",
    }["code-runner"]
    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    restriction_table = {
        "candidate": "candidate_subjects",
        "employer": "employer_subjects",
        "privacy": "processing_nonces",
        "assessment": "assessment_subjects",
        "coding-workspace": "workspace_subjects",
        "code-runner": "runner_subjects",
        "evaluation": "evaluation_subjects",
    }["code-runner"]
    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))
    connection.execute(text("SELECT 1 FROM runner_attempts LIMIT 0"))
    connection.execute(text("SELECT 1 FROM runner_results LIMIT 0"))
    connection.execute(text("SELECT 1 FROM validation_batches LIMIT 0"))
    connection.execute(text("SELECT 1 FROM validation_attempts LIMIT 0"))
    connection.execute(text("SELECT 1 FROM validation_captures LIMIT 0"))
    connection.execute(text("SELECT 1 FROM validation_verdicts LIMIT 0"))
    connection.execute(text("SELECT 1 FROM validation_work LIMIT 0"))
    connection.execute(text("SELECT 1 FROM submitted_jobs LIMIT 0"))
    connection.execute(text("SELECT 1 FROM submitted_attempts LIMIT 0"))
    connection.execute(text("SELECT 1 FROM runner_control LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="code-runner")
    if config.service_name != "code-runner":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
