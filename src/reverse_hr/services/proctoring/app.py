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

    from reverse_hr.protocols.stage_access import StageAccess
    from reverse_hr.services.proctoring.proctoring_internal import internal_router

    app.state.stage_access = StageAccess(config)
    app.include_router(internal_router)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "proctoring".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    for name in (
        "proctor_subjects",
        "proctor_streams",
        "proctor_events",
        "integrity_tracks",
        "integrity_reviews",
        "proctor_nonces",
    ):
        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="proctoring")
    if config.service_name != "proctoring":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
