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

from reverse_hr.platform.migrate import migration_config
from reverse_hr.platform.settings import Settings
from reverse_hr.shared.auth import TokenVerifier
from reverse_hr.shared.db import make_engine

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
    from reverse_hr.platform.registry import service_app

    service = service_app(config.service_name)
    service.configure(app, config, engine)

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
                service.check_ready(app, config, engine, connection)
        except Exception:
            return error(
                request, 503, "dependency_unavailable", "Database or migration unavailable"
            )
        return HealthResponse(status="ready", service=config.service_name)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(generate_latest(registry), media_type="text/plain; version=0.0.4")

    from reverse_hr.platform.openapi import preserve_schema_ids

    preserve_schema_ids(app)
    return app
