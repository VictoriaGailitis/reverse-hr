import logging
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import UUID, uuid4

from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CollectorRegistry, Counter, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.exceptions import HTTPException

from reverse_hr.auth import TokenVerifier
from reverse_hr.db import make_engine
from reverse_hr.migrate import migration_config
from reverse_hr.settings import SERVICES, Settings

logger = logging.getLogger("reverse_hr.http")


class ErrorResponse(BaseModel):
    code: str
    message: str
    fields: list[str] = Field(default_factory=list)
    trace_id: UUID


class HealthResponse(BaseModel):
    status: str
    service: str


def create_app(settings: Settings | None = None) -> FastAPI:
    config = settings or Settings()
    engine = make_engine(config.database_url.get_secret_value())
    expected_revision = ScriptDirectory.from_config(migration_config(config)).get_current_head()
    registry = CollectorRegistry()
    requests = Counter(
        "hr_http_requests_total", "HTTP responses", ["service", "status"], registry=registry
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        engine.dispose()

    app = FastAPI(
        title=f"Reverse HR / {config.service_name}",
        version="0.1.0",
        lifespan=lifespan,
        root_path=config.root_path,
        description="Service API; implemented routes are listed below.",
    )
    app.state.settings = config
    app.state.engine = engine
    app.state.token_verifier = TokenVerifier(config)
    if config.service_name in {
        "achievements",
        "integration",
        "demo-ats",
        "candidate",
        "employer",
        "assessment",
        "coding-workspace",
        "code-runner",
        "evaluation",
        "matching",
        "hiring",
        "notification",
        "media",
        "whiteboard",
        "proctoring",
        "audit",
        "identity",
    }:
        from reverse_hr.processing_access import ProcessingAccess

        app.state.processing_access = ProcessingAccess(config)
    if config.service_name in {
        "achievements",
        "integration",
        "demo-ats",
        "matching",
        "hiring",
        "candidate",
    }:
        from reverse_hr.exchange import ExchangeAccess
        from reverse_hr.market_access import MarketAccess

        app.state.exchange_access = ExchangeAccess(config)
        if config.service_name != "matching":
            app.state.market_access = MarketAccess(config)
    if config.service_name in {
        "achievements",
        "integration",
        "demo-ats",
        "demo-fsp",
        "demo-codenrock",
    }:
        from importlib import import_module

        module = (
            "demo_sources"
            if config.service_name in {"demo-fsp", "demo-codenrock"}
            else config.service_name.replace("-", "_")
        )
        domain = import_module("reverse_hr.domains." + module)
        app.include_router(domain.router)
        if hasattr(domain, "internal_router"):
            app.include_router(domain.internal_router)
    if config.service_name in {"media", "whiteboard", "proctoring", "coding-workspace"}:
        from importlib import import_module

        from reverse_hr.stage_access import StageAccess

        app.state.stage_access = StageAccess(config)

        @app.get("/v1/environment.js", response_class=Response, tags=["practical-ui"])
        def practical_ui():
            return Response(
                content=(Path(__file__).parent / "assets" / "practical.mjs").read_text(),
                media_type="text/javascript",
                headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
            )

    if config.service_name in {"media", "whiteboard"}:
        app.include_router(
            import_module("reverse_hr.domains." + config.service_name).internal_router
        )
        from reverse_hr.evaluation_artifact_access import ArtifactPermitAccess
        from reverse_hr.practical_export import router as practical_artifact_router

        app.include_router(practical_artifact_router)
        app.state.artifact_permit_access = ArtifactPermitAccess(config)
        if config.service_name == "media":
            from reverse_hr.media_antivirus import ClamdScanner
            from reverse_hr.media_decoder import IsolatedDecoder
            from reverse_hr.media_storage import configure
            from reverse_hr.media_transcription import router as transcription_router
            from reverse_hr.media_validation import FFmpegValidator
            from reverse_hr.recording_access import RecordingAccess
            from reverse_hr.recording_playback import internal_router as playback_internal_router

            configure(engine, config)
            app.state.media_validator = (
                IsolatedDecoder(config)
                if config.media_decoder_required or config.media_decoder_socket
                else FFmpegValidator(config)
            )
            app.state.media_scanner = (
                ClamdScanner(config) if config.media_antivirus_required else None
            )
            app.state.recording_access = RecordingAccess(config)
            app.include_router(transcription_router)
            app.include_router(playback_internal_router)
    if config.service_name == "proctoring":
        from reverse_hr.proctoring_internal import internal_router
        from reverse_hr.stage_access import StageAccess

        app.state.stage_access = StageAccess(config)
        app.include_router(internal_router)
    if config.service_name == "evaluation":
        from reverse_hr.proctoring_access import IntegrityAccess
        from reverse_hr.proctoring_access import router as integrity_router

        app.state.integrity_access = IntegrityAccess(config)
        app.include_router(integrity_router)
    if config.service_name == "privacy":
        from reverse_hr.backup_archive import configure as configure_backups

        configure_backups(engine, config)
    if config.service_name == "candidate":
        from reverse_hr.domains import (
            candidate_grades,  # noqa: F401
            candidate_preferences,  # noqa: F401
            candidate_resume,
        )
        from reverse_hr.media_antivirus import ClamdScanner
        from reverse_hr.resume_access import PDFGuest

        candidate_resume.configure(engine, config)
        app.state.resume_guest = PDFGuest(config)
        app.state.resume_scanner = (
            ClamdScanner(config) if config.resume_antivirus_required else None
        )
        app.include_router(candidate_resume.router)

    if config.service_name == "code-runner":
        from reverse_hr.runner_exchange import ManifestAccess
        from reverse_hr.suite_admission import SuiteAdmissionAccess
        from reverse_hr.verdict_delivery import VerdictDeliveryAccess

        app.state.manifest_access = ManifestAccess(config)
        app.state.suite_admission = SuiteAdmissionAccess(config)
        app.state.verdict_delivery = VerdictDeliveryAccess(config)
    if config.service_name in {"code-runner", "coding-workspace"}:
        from reverse_hr.submitted_access import SubmittedAccess

        app.state.submitted_access = SubmittedAccess(config)
    if config.service_name == "assessment":
        from reverse_hr.grade_access import GradeAccess

        app.state.grade_access = GradeAccess(config)
        from reverse_hr.snapshot_access import SnapshotAccess

        app.state.snapshot_access = SnapshotAccess(config)
        from reverse_hr.practical_receipts import PracticalReceiptAccess

        app.state.practical_receipt_access = PracticalReceiptAccess(config)
    if config.service_name == "evaluation":
        from reverse_hr.evaluation_access import MaterialAccess
        from reverse_hr.evaluation_artifact_access import ArtifactAccess

        app.state.material_access = MaterialAccess(config)
        from reverse_hr.recording_playback import PlaybackAccess
        from reverse_hr.recording_playback import router as playback_router

        app.state.playback_access = PlaybackAccess(config)
        app.include_router(playback_router)
        from reverse_hr.evaluation_recovery import router as recovery_router

        app.include_router(recovery_router)
        app.state.artifact_access = ArtifactAccess(config)
    if config.service_name == "coding-workspace":
        from reverse_hr.evaluation_artifact_access import ArtifactPermitAccess
        from reverse_hr.stage_access import StageAccess

        app.state.stage_access = StageAccess(config)
        app.state.artifact_permit_access = ArtifactPermitAccess(config)
    if config.service_name in {
        "candidate",
        "hiring",
        "matching",
        "notification",
        "assessment",
        "evaluation",
    }:
        from reverse_hr.market_access import MarketAccess

        app.state.market_access = MarketAccess(config)
    if config.service_name == "identity" and config.identity_export_enabled:
        from reverse_hr.identity_export import KeycloakIdentityExport

        provider = KeycloakIdentityExport(config)
        app.state.identity_export_provider = engine.identity_export_provider = provider
    if config.service_name == "notification":
        from reverse_hr.domains.notification_delivery import (
            internal_router as callback_router,
        )
        from reverse_hr.domains.notification_delivery import (
            router as delivery_router,
        )

        app.include_router(delivery_router)
        app.include_router(callback_router)
    if config.service_name == "candidate":
        from reverse_hr.domains.candidate_market import internal_router as market_router

        app.include_router(market_router)
    if config.service_name == "candidate":
        from reverse_hr.qualification_policy_access import QualificationPolicyAccess

        app.state.qualification_policy_access = QualificationPolicyAccess(config)
    if config.service_name in SERVICES:
        from reverse_hr.privacy_request_exchange import RightsAccess
        from reverse_hr.privacy_request_exchange import router as rights_exchange_router

        app.state.rights_access = RightsAccess(config)
        app.include_router(rights_exchange_router)
    if config.service_name == "privacy":
        from reverse_hr.domains.privacy_market import router as market_router

        app.include_router(market_router)
        from reverse_hr.domains.privacy_company_results import router as company_results_router

        app.include_router(company_results_router)
        from reverse_hr.domains.privacy_requests import router as subject_requests_router

        app.include_router(subject_requests_router)
        from reverse_hr.domains.privacy_archives import router as archives_router

        app.include_router(archives_router)
    if config.service_name == "employer":
        from reverse_hr.domains.employer_market import router as market_router
        from reverse_hr.domains.employer_trust import router as trust_router

        app.include_router(market_router)
        app.include_router(trust_router)
    if config.service_name == "hiring":
        from reverse_hr.domains import (  # noqa: F401
            hiring_communication_risk,
            hiring_dialogs,
            hiring_moderation,
            hiring_trust,
            hiring_vacancies,
        )
        from reverse_hr.domains.hiring import internal_router as market_router

        app.include_router(market_router)
        app.include_router(hiring_vacancies.router)
    if config.service_name in (
        "candidate",
        "privacy",
        "employer",
        "assessment",
        "coding-workspace",
        "code-runner",
        "evaluation",
        "matching",
        "hiring",
        "notification",
        "media",
        "whiteboard",
        "proctoring",
        "audit",
    ):
        from importlib import import_module

        domain_name = config.service_name.replace("-", "_")
        domain = import_module(f"reverse_hr.domains.{domain_name}")
        app.include_router(
            domain.router,
            responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
        )
        if config.service_name == "audit":
            app.include_router(domain.internal_router)
        if config.service_name == "assessment":
            app.include_router(import_module("reverse_hr.domains.assessment_selection").router)
            app.include_router(import_module("reverse_hr.domains.company_tasks").router)
            app.include_router(import_module("reverse_hr.domains.company_assignments").router)
            app.include_router(import_module("reverse_hr.domains.company_schedules").router)
            app.include_router(
                import_module("reverse_hr.domains.assessment_sessions").router,
                responses={
                    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
                },
            )

    if config.service_name in {"hiring", "employer", "assessment"}:
        from reverse_hr import review_sla

        app.include_router(getattr(review_sla, config.service_name + "_router"))
    if config.service_name == "evaluation":
        from reverse_hr.evaluation_llm import router as model_router

        app.include_router(model_router)
        from reverse_hr.domains.evaluation_scores import router as stage_scores_router

        app.include_router(stage_scores_router)
        from reverse_hr.domains.evaluation_tests import router as test_results_router

        app.include_router(test_results_router)
        from reverse_hr.domains.evaluation_review import router as review_router

        app.include_router(
            review_router,
            responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
        )
    if config.service_name == "matching":
        from reverse_hr.qualification_policy_access import router as qualification_policy_router

        app.include_router(qualification_policy_router)
        app.state.matching_intent_gateway = None
        if config.matching_llm_enabled:
            from reverse_hr.matching_gateway import MatchingIntentGateway

            app.state.matching_intent_gateway = MatchingIntentGateway(config)
    if config.service_name == "hiring":
        from reverse_hr.domains.hiring_ats import router as ats_router

        app.include_router(ats_router)
    if config.service_name == "assessment":
        from reverse_hr.domains.assessment_grades import router as grade_router

        app.include_router(grade_router)
        from reverse_hr.domains.assessment_appeals import internal_router as appeal_notices_router
        from reverse_hr.domains.assessment_appeals import router as appeals_router

        app.include_router(appeal_notices_router)

        app.include_router(appeals_router)
        from reverse_hr.domains.assessment_confirmed_grade import router as confirmed_router

        app.include_router(confirmed_router)
        from reverse_hr.domains.assessment_submitted import router as submitted_router

        app.include_router(submitted_router)
        from reverse_hr.domains.assessment_evaluation import router as material_router
        from reverse_hr.domains.assessment_lifecycle import router as lifecycle_router
        from reverse_hr.domains.assessment_suite_admission import router as suite_admission_router
        from reverse_hr.domains.assessment_tests import router as tests_router
        from reverse_hr.domains.assessment_verdicts import router as verdicts_router

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
            material_router,
            responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
        )
        app.include_router(
            lifecycle_router,
            responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
        )
        from reverse_hr.domains.assessment_workspace import router as workspace_admission_router

        app.include_router(
            workspace_admission_router,
            responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
        )

    if config.service_name == "coding-workspace":
        from reverse_hr.domains.workspace_submitted import router as submitted_source_router

        app.include_router(submitted_source_router)
        from reverse_hr.domains.workspace_evaluation import router as artifact_router
        from reverse_hr.domains.workspace_runner import router as manifest_router
        from reverse_hr.domains.workspace_snapshot import router as snapshot_router

        app.include_router(
            artifact_router,
            responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
        )
        app.include_router(
            snapshot_router,
            responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
        )
        app.include_router(
            manifest_router,
            responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)},
        )

    def error(request: Request, status: int, code: str, message: str, fields=None):
        return JSONResponse(
            status_code=status,
            content=ErrorResponse(
                code=code,
                message=message,
                fields=fields or [],
                trace_id=request.state.trace_id,
            ).model_dump(mode="json"),
        )

    @app.middleware("http")
    async def correlation(request: Request, call_next):
        try:
            trace = UUID(request.headers.get("X-Request-ID", ""))
        except ValueError:
            trace = uuid4()
        request.state.trace_id = trace
        try:
            response = await call_next(request)
        except Exception:
            # Do not log exception text: DB URLs, request values or PII may be present.
            logger.error("request_failed service=%s trace_id=%s", config.service_name, trace)
            response = error(request, 500, "internal_error", "Internal server error")
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Request-ID"] = str(trace)
        requests.labels(config.service_name, str(response.status_code)).inc()
        return response

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError):
        fields = [".".join(map(str, item["loc"])) for item in exc.errors()]
        return error(request, 422, "validation_error", "Invalid request", fields)

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        codes = {401: "unauthenticated", 403: "forbidden", 404: "not_found", 409: "conflict"}
        return error(
            request,
            exc.status_code,
            codes.get(exc.status_code, "http_error"),
            "Request could not be completed",
        )

    @app.get("/health/live", response_model=HealthResponse)
    def live():
        return HealthResponse(status="ok", service=config.service_name)

    @app.get(
        "/health/ready", response_model=HealthResponse, responses={503: {"model": ErrorResponse}}
    )
    def ready(request: Request):
        try:
            with engine.connect() as connection:
                current_revision = connection.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar_one()
                if current_revision != expected_revision:
                    raise RuntimeError("Migration revision unavailable")
                connection.execute(text("SELECT event_id FROM outbox LIMIT 0"))
                if config.service_name in {"media", "whiteboard"}:
                    tables = (
                        (
                            "media_subjects",
                            "recordings",
                            "recording_chunks",
                            "media_nonces",
                            "media_transcripts",
                            "media_transcription_attempts",
                            "media_storage_identity",
                        )
                        if config.service_name == "media"
                        else (
                            "board_subjects",
                            "boards",
                            "board_operations",
                            "board_snapshots",
                            "board_nonces",
                        )
                    )
                    for name in tables:
                        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))
                if config.service_name == "audit":
                    from reverse_hr.domains.audit import AuditBase

                    for table in AuditBase.metadata.sorted_tables:
                        connection.execute(text(f"SELECT 1 FROM {table.name} LIMIT 0"))
                if config.service_name == "candidate":
                    connection.execute(text("SELECT version FROM candidate_contacts LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM candidate_preferences LIMIT 0"))
                if config.service_name == "media":
                    if getattr(engine, "media_store", None) is None:
                        raise RuntimeError("Media storage unavailable")
                    if config.media_antivirus_required:
                        app.state.media_scanner.ready()
                    if config.media_decoder_required:
                        app.state.media_validator.ready()
                if config.service_name in {
                    "achievements",
                    "integration",
                    "demo-ats",
                    "demo-fsp",
                    "demo-codenrock",
                }:
                    from importlib import import_module

                    module = (
                        "demo_sources"
                        if config.service_name in {"demo-fsp", "demo-codenrock"}
                        else config.service_name.replace("-", "_")
                    )
                    domain = import_module("reverse_hr.domains." + module)
                    base = {
                        "achievements": "AchievementsBase",
                        "integration": "IntegrationBase",
                        "demo-ats": "DemoATSBase",
                        "demo-fsp": "DemoSourceBase",
                        "demo-codenrock": "DemoSourceBase",
                    }[config.service_name]
                    for table in getattr(domain, base).metadata.sorted_tables:
                        connection.execute(text(f"SELECT 1 FROM {table.name} LIMIT 0"))
                if config.service_name == "hiring":
                    connection.execute(text("SELECT 1 FROM hiring_ats_statuses LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM hiring_employer_reviews LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM hiring_moderation_appeals LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM hiring_invitation_revisions LIMIT 0"))
                if config.service_name == "employer":
                    for table in (
                        "employer_trust_decisions",
                        "employer_sanctions",
                        "employer_trust_appeals",
                    ):
                        connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
                if config.service_name == "notification":
                    connection.execute(
                        text(
                            "SELECT appeal_id, owner, category, assignment_id, application_id "
                            "FROM notification_notices LIMIT 0"
                        )
                    )
                    connection.execute(
                        text("SELECT marketing_in_app FROM notification_preferences LIMIT 0")
                    )
                if config.service_name in {"hiring", "employer", "assessment"}:
                    for suffix in ("review_pool", "review_sla", "review_actions"):
                        connection.execute(
                            text(f"SELECT 1 FROM {config.service_name}_{suffix} LIMIT 0")
                        )
                if config.service_name == "hiring":
                    connection.execute(text("SELECT 1 FROM hiring_communication_risks LIMIT 0"))
                if config.service_name == "privacy":
                    connection.execute(text("SELECT 1 FROM company_result_grants LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM privacy_subject_requests LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM privacy_request_history LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM privacy_archives LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM privacy_archive_pages LIMIT 0"))
                    connection.execute(text("SELECT 1 FROM backup_store_identity LIMIT 0"))
                    from reverse_hr.backup_archive import bind as backup_bind

                    with Session(engine) as session, session.begin():
                        backup_bind(session)
                if config.service_name == "proctoring":
                    for name in (
                        "proctor_subjects",
                        "proctor_streams",
                        "proctor_events",
                        "integrity_tracks",
                        "integrity_reviews",
                        "proctor_nonces",
                    ):
                        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))
                if config.service_name == "notification":
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
                if config.service_name in {"matching", "hiring"}:
                    names = (
                        (
                            "matching_candidates",
                            "matching_snapshots",
                            "matching_subjects",
                            "matching_governance_versions",
                            "matching_intent_previews",
                            "matching_policy_nonces",
                        )
                        if config.service_name == "matching"
                        else (
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
                    )
                    for name in names:
                        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))
                if config.service_name in (
                    "candidate",
                    "privacy",
                    "employer",
                    "assessment",
                    "coding-workspace",
                    "code-runner",
                    "evaluation",
                ):
                    table = {
                        "candidate": "candidate_profiles",
                        "privacy": "consents",
                        "employer": "organizations",
                        "assessment": "content_revisions",
                        "coding-workspace": "workspaces",
                        "code-runner": "runner_jobs",
                        "evaluation": "evaluation_intakes",
                    }[config.service_name]
                    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
                    restriction_table = {
                        "candidate": "candidate_subjects",
                        "employer": "employer_subjects",
                        "privacy": "processing_nonces",
                        "assessment": "assessment_subjects",
                        "coding-workspace": "workspace_subjects",
                        "code-runner": "runner_subjects",
                        "evaluation": "evaluation_subjects",
                    }[config.service_name]
                    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))
                    if config.service_name == "employer":
                        connection.execute(text("SELECT 1 FROM ownership_recoveries LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM employer_market_nonces LIMIT 0"))
                    if config.service_name == "candidate":
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
                    if config.service_name == "assessment":
                        for table in (
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
                            text(
                                "SELECT grade_policy_id, grade_policy_digest "
                                "FROM assessment_sessions LIMIT 0"
                            )
                        )
                        connection.execute(text("SELECT 1 FROM grade_policies LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM grade_decisions LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM candidate_grades LIMIT 0"))
                        connection.execute(
                            text("SELECT test_pins, test_pins_digest FROM plan_versions LIMIT 0")
                        )
                        connection.execute(
                            text(
                                "SELECT test_pins, test_pins_digest "
                                "FROM assessment_sessions LIMIT 0"
                            )
                        )
                        connection.execute(text("SELECT 1 FROM assessment_stages LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM stage_nonces LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM material_nonces LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM test_suites LIMIT 0"))
                        connection.execute(
                            text(
                                "SELECT attestation, attestation_signature "
                                "FROM suite_validation_intakes LIMIT 0"
                            )
                        )
                    if config.service_name == "evaluation":
                        connection.execute(text("SELECT 1 FROM evaluation_reviews LIMIT 0"))
                        connection.execute(
                            text(
                                "SELECT gateway_configuration "
                                "FROM evaluation_model_attempts LIMIT 0"
                            )
                        )
                        connection.execute(text("SELECT 1 FROM evaluation_test_evidence LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM evaluation_result_nonces LIMIT 0"))
                        connection.execute(
                            text("SELECT score, review_number FROM evaluation_intakes LIMIT 0")
                        )
                        connection.execute(
                            text(
                                "SELECT source, requirements, artifact_attempts, "
                                "artifact_available_at "
                                "FROM evaluation_intakes LIMIT 0"
                            )
                        )
                        connection.execute(
                            text(
                                "SELECT material, material_attempts, material_available_at "
                                "FROM evaluation_intakes LIMIT 0"
                            )
                        )
                    if config.service_name == "code-runner":
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
                    if config.service_name == "coding-workspace":
                        connection.execute(text("SELECT 1 FROM workspace_snapshots LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM workspace_runs LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM runner_nonces LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM snapshot_nonces LIMIT 0"))
                        connection.execute(text("SELECT 1 FROM artifact_nonces LIMIT 0"))
        except Exception:
            return error(
                request, 503, "dependency_unavailable", "Database or migration unavailable"
            )
        if config.service_name == "candidate" and config.resume_storage_root:
            try:
                from reverse_hr.domains.candidate_resume import storage

                with Session(engine) as session, session.begin():
                    storage(session)
                app.state.resume_guest.ready()
                if config.resume_antivirus_required:
                    app.state.resume_scanner.ready()
            except Exception as exc:
                raise HTTPException(503) from exc
        return HealthResponse(status="ready", service=config.service_name)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    return app
