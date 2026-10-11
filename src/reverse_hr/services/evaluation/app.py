from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.proctoring_access import IntegrityAccess
    from reverse_hr.protocols.proctoring_access import router as integrity_router

    app.state.integrity_access = IntegrityAccess(config)
    app.include_router(integrity_router)
    from reverse_hr.protocols.evaluation_access import MaterialAccess
    from reverse_hr.protocols.evaluation_artifact_access import ArtifactAccess

    app.state.material_access = MaterialAccess(config)
    from reverse_hr.protocols.recording_playback import PlaybackAccess
    from reverse_hr.protocols.recording_playback import router as playback_router

    app.state.playback_access = PlaybackAccess(config)
    app.include_router(playback_router)
    from reverse_hr.services.evaluation.evaluation_recovery import router as recovery_router

    app.include_router(recovery_router)
    app.state.artifact_access = ArtifactAccess(config)
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.market_access = MarketAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "evaluation".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    from reverse_hr.services.evaluation.evaluation_automatic import router as automatic_router

    app.include_router(automatic_router)
    from reverse_hr.services.evaluation.evaluation_risk import router as risk_router

    app.include_router(risk_router)
    from reverse_hr.services.evaluation.evaluation_llm import router as model_router

    app.include_router(model_router)
    from reverse_hr.services.evaluation.domain.evaluation_scores import (
        router as stage_scores_router,
    )

    app.include_router(stage_scores_router)
    from reverse_hr.services.evaluation.domain.evaluation_tests import router as test_results_router

    app.include_router(test_results_router)
    from reverse_hr.services.evaluation.domain.evaluation_review import router as review_router

    app.include_router(
        review_router,
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
    }["evaluation"]
    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    restriction_table = {
        "candidate": "candidate_subjects",
        "employer": "employer_subjects",
        "privacy": "processing_nonces",
        "assessment": "assessment_subjects",
        "coding-workspace": "workspace_subjects",
        "code-runner": "runner_subjects",
        "evaluation": "evaluation_subjects",
    }["evaluation"]
    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))
    connection.execute(text("SELECT 1 FROM evaluation_reviews LIMIT 0"))
    connection.execute(text("SELECT 1 FROM evaluation_automatic_reviews LIMIT 0"))
    connection.execute(text("SELECT 1 FROM evaluation_risks LIMIT 0"))
    connection.execute(text("SELECT gateway_configuration FROM evaluation_model_attempts LIMIT 0"))
    connection.execute(text("SELECT 1 FROM evaluation_test_evidence LIMIT 0"))
    connection.execute(text("SELECT 1 FROM evaluation_result_nonces LIMIT 0"))
    connection.execute(text("SELECT score, review_number FROM evaluation_intakes LIMIT 0"))
    connection.execute(
        text(
            "SELECT source, requirements, artifact_attempts, artifact_available_at "
            "FROM evaluation_intakes LIMIT 0"
        )
    )
    connection.execute(
        text(
            "SELECT material, material_attempts, material_available_at "
            "FROM evaluation_intakes LIMIT 0"
        )
    )


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="evaluation")
    if config.service_name != "evaluation":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
