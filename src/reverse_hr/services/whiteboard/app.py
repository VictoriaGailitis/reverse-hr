from pathlib import Path

from fastapi import Response
from sqlalchemy import text

from reverse_hr.platform.app import ErrorResponse
from reverse_hr.platform.registry import domain_module
from reverse_hr.platform.settings import Settings


def configure(app, config, engine):
    from reverse_hr.protocols.processing_access import ProcessingAccess

    app.state.processing_access = ProcessingAccess(config)
    from reverse_hr.protocols.stage_access import StageAccess

    app.state.stage_access = StageAccess(config)

    @app.get("/v1/environment.js", response_class=Response, tags=["practical-ui"])
    def practical_ui():
        return Response(
            content=(
                Path(__file__).resolve().parents[2] / "shared/assets/practical.mjs"
            ).read_text(),
            media_type="text/javascript",
            headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"},
        )

    app.include_router(domain_module("whiteboard").internal_router)
    from reverse_hr.protocols.evaluation_artifact_access import ArtifactPermitAccess
    from reverse_hr.protocols.practical_export import router as practical_artifact_router

    app.include_router(practical_artifact_router)
    app.state.artifact_permit_access = ArtifactPermitAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "whiteboard".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    tables = ("board_subjects", "boards", "board_operations", "board_snapshots", "board_nonces")
    for name in tables:
        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="whiteboard")
    if config.service_name != "whiteboard":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
