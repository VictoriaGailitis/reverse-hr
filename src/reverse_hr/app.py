import logging
from contextlib import asynccontextmanager
from uuid import UUID, uuid4

from alembic.script import ScriptDirectory
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from prometheus_client import CollectorRegistry, Counter, generate_latest
from pydantic import BaseModel, Field
from sqlalchemy import text
from starlette.exceptions import HTTPException

from reverse_hr.auth import TokenVerifier
from reverse_hr.db import make_engine
from reverse_hr.migrate import migration_config
from reverse_hr.settings import Settings

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
        "candidate",
        "employer",
        "assessment",
        "coding-workspace",
        "code-runner",
        "evaluation",
    }:
        from reverse_hr.processing_access import ProcessingAccess

        app.state.processing_access = ProcessingAccess(config)
    if config.service_name == "code-runner":
        from reverse_hr.runner_exchange import ManifestAccess
        from reverse_hr.suite_admission import SuiteAdmissionAccess
        from reverse_hr.verdict_delivery import VerdictDeliveryAccess

        app.state.manifest_access = ManifestAccess(config)
        app.state.suite_admission = SuiteAdmissionAccess(config)
        app.state.verdict_delivery = VerdictDeliveryAccess(config)
    if config.service_name == "assessment":
        from reverse_hr.snapshot_access import SnapshotAccess

        app.state.snapshot_access = SnapshotAccess(config)
    if config.service_name == "evaluation":
        from reverse_hr.evaluation_access import MaterialAccess
        from reverse_hr.evaluation_artifact_access import ArtifactAccess

        app.state.material_access = MaterialAccess(config)
        app.state.artifact_access = ArtifactAccess(config)
    if config.service_name == "coding-workspace":
        from reverse_hr.evaluation_artifact_access import ArtifactPermitAccess
        from reverse_hr.stage_access import StageAccess

        app.state.stage_access = StageAccess(config)
        app.state.artifact_permit_access = ArtifactPermitAccess(config)
    if config.service_name in (
        "candidate",
        "privacy",
        "employer",
        "assessment",
        "coding-workspace",
        "code-runner",
        "evaluation",
    ):
        from importlib import import_module

        domain_name = config.service_name.replace("-", "_")
        domain = import_module(f"reverse_hr.domains.{domain_name}")
        app.include_router(
            domain.router,
            responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
        )
        if config.service_name == "assessment":
            app.include_router(
                import_module("reverse_hr.domains.assessment_sessions").router,
                responses={
                    code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)
                },
            )

    if config.service_name == "evaluation":
        from reverse_hr.domains.evaluation_review import router as review_router

        app.include_router(
            review_router,
            responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
        )
    if config.service_name == "assessment":
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
                    if config.service_name == "assessment":
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
        return HealthResponse(status="ready", service=config.service_name)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    return app
