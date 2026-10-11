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

    from reverse_hr.protocols.submitted_access import SubmittedAccess

    app.state.submitted_access = SubmittedAccess(config)
    from reverse_hr.protocols.evaluation_artifact_access import ArtifactPermitAccess
    from reverse_hr.protocols.stage_access import StageAccess

    app.state.stage_access = StageAccess(config)
    app.state.artifact_permit_access = ArtifactPermitAccess(config)
    from reverse_hr.coordination.privacy_request_exchange import RightsAccess
    from reverse_hr.coordination.privacy_request_exchange import router as rights_exchange_router

    app.state.rights_access = RightsAccess(config)
    app.include_router(rights_exchange_router)
    domain_name = "coding-workspace".replace("-", "_")
    domain = domain_module(domain_name)
    app.include_router(
        domain.router,
        responses={code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)},
    )
    from reverse_hr.services.coding_workspace.domain.workspace_submitted import (
        router as submitted_source_router,
    )

    app.include_router(submitted_source_router)
    from reverse_hr.services.coding_workspace.domain.workspace_evaluation import (
        router as artifact_router,
    )
    from reverse_hr.services.coding_workspace.domain.workspace_runner import (
        router as manifest_router,
    )
    from reverse_hr.services.coding_workspace.domain.workspace_snapshot import (
        router as snapshot_router,
    )

    app.include_router(
        artifact_router, responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)}
    )
    app.include_router(
        snapshot_router, responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)}
    )
    app.include_router(
        manifest_router, responses={code: {"model": ErrorResponse} for code in (401, 409, 422, 503)}
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
    }["coding-workspace"]
    connection.execute(text(f"SELECT 1 FROM {table} LIMIT 0"))
    restriction_table = {
        "candidate": "candidate_subjects",
        "employer": "employer_subjects",
        "privacy": "processing_nonces",
        "assessment": "assessment_subjects",
        "coding-workspace": "workspace_subjects",
        "code-runner": "runner_subjects",
        "evaluation": "evaluation_subjects",
    }["coding-workspace"]
    connection.execute(text(f"SELECT 1 FROM {restriction_table} LIMIT 0"))
    connection.execute(text("SELECT 1 FROM workspace_snapshots LIMIT 0"))
    connection.execute(text("SELECT 1 FROM workspace_runs LIMIT 0"))
    connection.execute(text("SELECT 1 FROM runner_nonces LIMIT 0"))
    connection.execute(text("SELECT 1 FROM snapshot_nonces LIMIT 0"))
    connection.execute(text("SELECT 1 FROM artifact_nonces LIMIT 0"))


def create_app(settings=None):
    from reverse_hr.platform.app import create_app as build_app

    config = settings or Settings(service_name="coding-workspace")
    if config.service_name != "coding-workspace":
        raise ValueError("Service entry point does not match configuration")
    return build_app(config)
