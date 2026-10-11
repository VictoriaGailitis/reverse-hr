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

    app.include_router(domain_module("media").internal_router)
    from reverse_hr.protocols.evaluation_artifact_access import ArtifactPermitAccess
    from reverse_hr.protocols.practical_export import router as practical_artifact_router

    app.include_router(practical_artifact_router)
    app.state.artifact_permit_access = ArtifactPermitAccess(config)
    from reverse_hr.protocols.recording_access import RecordingAccess
    from reverse_hr.protocols.recording_playback import internal_router as playback_internal_router
    from reverse_hr.services.media.media_decoder import IsolatedDecoder
    from reverse_hr.services.media.media_storage import configure
    from reverse_hr.services.media.media_transcription import router as transcription_router
    from reverse_hr.services.media.media_validation import FFmpegValidator
    from reverse_hr.shared.media_antivirus import ClamdScanner

    configure(engine, config)
    app.state.media_validator = (
        IsolatedDecoder(config)
        if config.media_decoder_required or config.media_decoder_socket
        else FFmpegValidator(config)
    )
    app.state.media_scanner = ClamdScanner(config) if config.media_antivirus_required else None
    app.state.recording_access = RecordingAccess(config)
    app.include_router(transcription_router)
    app.include_router(playback_internal_router)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "media".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )


def check_ready(app, config, engine, connection):
    tables = (
        "media_subjects",
        "recordings",
        "recording_chunks",
        "media_nonces",
        "media_transcripts",
        "media_transcription_attempts",
        "media_storage_identity",
    )
    for name in tables:
        connection.execute(text(f"SELECT 1 FROM {name} LIMIT 0"))
    if getattr(engine, "media_store", None) is None:
        raise RuntimeError("Media storage unavailable")
    if config.media_antivirus_required:
        app.state.media_scanner.ready()
    if config.media_decoder_required:
        app.state.media_validator.ready()


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="media")
    if config.service_name != "media":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
