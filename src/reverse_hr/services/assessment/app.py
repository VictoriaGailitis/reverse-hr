from importlib import import_module

from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.grade_access import GradeAccess

    app.state.grade_access = GradeAccess(config)
    from reverse_hr.protocols.snapshot_access import SnapshotAccess

    app.state.snapshot_access = SnapshotAccess(config)
    from reverse_hr.protocols.practical_receipts import PracticalReceiptAccess

    app.state.practical_receipt_access = PracticalReceiptAccess(config)
    from reverse_hr.protocols.market_access import MarketAccess

    app.state.market_access = MarketAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "assessment".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    app.include_router(
        import_module("reverse_hr.services.assessment.domain.assessment_selection").router
    )
    app.include_router(import_module("reverse_hr.services.assessment.domain.company_tasks").router)
    app.include_router(
        import_module("reverse_hr.services.assessment.domain.company_assignments").router
    )
    app.include_router(
        import_module("reverse_hr.services.assessment.domain.company_schedules").router
    )
    app.include_router(
        import_module("reverse_hr.services.assessment.domain.assessment_sessions").router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    from reverse_hr.coordination import review_sla

    app.include_router(review_sla.make_router("assessment"))
    from reverse_hr.protocols.generated_validation import router as generated_validation_router
    from reverse_hr.services.assessment.domain.assessment_automatic import (
        router as automatic_router,
    )
    from reverse_hr.services.assessment.domain.assessment_generation import (
        router as generation_router,
    )

    app.include_router(generation_router)
    from reverse_hr.services.assessment.task_catalog import router as catalog_router

    app.include_router(catalog_router)
    app.include_router(automatic_router)
    app.include_router(generated_validation_router)
    from reverse_hr.services.assessment.domain.assessment_grades import router as grade_router

    app.include_router(grade_router)
    from reverse_hr.services.assessment.domain.task_analytics import router as analytics_router

    app.include_router(analytics_router)
    from reverse_hr.services.assessment.domain.assessment_appeals import (
        internal_router as appeal_notices_router,
    )
    from reverse_hr.services.assessment.domain.assessment_appeals import router as appeals_router

    app.include_router(appeal_notices_router)
    app.include_router(appeals_router)
    from reverse_hr.services.assessment.domain.assessment_confirmed_grade import (
        router as confirmed_router,
    )

    app.include_router(confirmed_router)
    from reverse_hr.services.assessment.domain.assessment_submitted import (
        router as submitted_router,
    )

    app.include_router(submitted_router)
    from reverse_hr.services.assessment.domain.assessment_evaluation import (
        router as material_router,
    )
    from reverse_hr.services.assessment.domain.assessment_lifecycle import (
        router as lifecycle_router,
    )
    from reverse_hr.services.assessment.domain.assessment_suite_admission import (
        router as suite_admission_router,
    )
    from reverse_hr.services.assessment.domain.assessment_tests import router as tests_router
    from reverse_hr.services.assessment.domain.assessment_verdicts import router as verdicts_router

    app.include_router(
        verdicts_router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    app.include_router(
        suite_admission_router,
        responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
    )
    app.include_router(
        tests_router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    app.include_router(
        material_router, responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)}
    )
    app.include_router(
        lifecycle_router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    from reverse_hr.services.assessment.domain.assessment_workspace import (
        router as workspace_admission_router,
    )

    app.include_router(
        workspace_admission_router,
        responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    for suffix in ("review_pool", "review_sla", "review_actions"):
        connection.execute(text(f"SELECT 1 FROM {'assessment'}_{suffix} LIMIT 0"))
    table = {
        "candidate": "candidate_profiles",
        "privacy": "consents",
        "employer": "organizations",
        "assessment": "content_revisions",
        "coding-workspace": "workspaces",
        "code-runner": "runner_jobs",
        "evaluation": "evaluation_intakes",
    }["assessment"]
    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    restriction_table = {
        "candidate": "candidate_subjects",
        "employer": "employer_subjects",
        "privacy": "processing_nonces",
        "assessment": "assessment_subjects",
        "coding-workspace": "workspace_subjects",
        "code-runner": "runner_subjects",
        "evaluation": "evaluation_subjects",
    }["assessment"]
    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))
    for table in (
        "assessment_generation_references",
        "assessment_generation_previews",
        "assessment_generation_jobs",
        "assessment_automatic_reviews",
        "assessment_selection_policies",
        "assessment_variant_templates",
        "assessment_generated_variants",
        "assessment_appeals",
        "assessment_appeal_actions",
        "assessment_appeal_decisions",
        "assessment_appeal_notices",
        "company_subscriptions",
        "company_schedules",
        "company_jobs",
        "company_notice_sources",
        "company_assignment_origins",
        "company_delivery_limits",
    ):
        connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    connection.execute(text("SELECT 1 FROM company_assignments LIMIT 0"))
    connection.execute(text("SELECT 1 FROM company_task_proposals LIMIT 0"))
    connection.execute(
        text("SELECT grade_policy_id, grade_policy_digest FROM assessment_sessions LIMIT 0")
    )
    connection.execute(text("SELECT 1 FROM grade_policies LIMIT 0"))
    connection.execute(text("SELECT 1 FROM grade_decisions LIMIT 0"))
    connection.execute(text("SELECT 1 FROM candidate_grades LIMIT 0"))
    connection.execute(text("SELECT test_pins, test_pins_digest FROM plan_versions LIMIT 0"))
    connection.execute(text("SELECT test_pins, test_pins_digest FROM assessment_sessions LIMIT 0"))
    connection.execute(text("SELECT 1 FROM assessment_stages LIMIT 0"))
    connection.execute(text("SELECT 1 FROM stage_nonces LIMIT 0"))
    connection.execute(text("SELECT 1 FROM material_nonces LIMIT 0"))
    connection.execute(text("SELECT 1 FROM test_suites LIMIT 0"))
    connection.execute(
        text("SELECT attestation, attestation_signature FROM suite_validation_intakes LIMIT 0")
    )


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="assessment")
    if config.service_name != "assessment":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
