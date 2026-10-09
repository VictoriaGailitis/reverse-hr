"""Export runtime OpenAPI and an explicitly proposed first-scenario OpenAPI."""

import json
from pathlib import Path
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Header
from fastapi import Path as ApiPath
from fastapi.security import HTTPBearer

from reverse_hr import contracts as dto
from reverse_hr.app import ErrorResponse, create_app
from reverse_hr.events import EventEnvelope
from reverse_hr.settings import SIGNING_SERVICES, Settings

root = Path("contracts")
root.mkdir(exist_ok=True)


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


for service in SIGNING_SERVICES:
    app = create_app(Settings(service_name=service))
    write(root / f"{service}.openapi.json", app.openapi())
    app.state.engine.dispose()

proposed = FastAPI(
    title="Reverse HR / first scenario (PROPOSED)",
    version="1.0.0-draft",
    description="Design contract only. These business routes are not served by the skeleton.",
    dependencies=[Depends(HTTPBearer())],
)
errors = {code: {"model": ErrorResponse} for code in (401, 403, 404, 409, 422, 503)}
command = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
version = Annotated[str, Header(alias="If-Match", pattern=r'^"[1-9][0-9]*"$')]
object_id = Annotated[UUID, ApiPath()]


@proposed.get("/v1/candidates/me", response_model=dto.Profile, responses=errors)
def profile():
    pass


@proposed.put("/v1/candidates/me", response_model=dto.Profile, responses=errors)
def update_profile(body: dto.ProfileUpdate, idempotency: command, if_match: version):
    pass


@proposed.post("/v1/consents", response_model=dto.Consent, status_code=201, responses=errors)
def consent(body: dto.ConsentCommand, idempotency: command):
    pass


@proposed.post("/v1/consents/{consent_id}/revoke", response_model=dto.Consent, responses=errors)
def revoke_consent(consent_id: object_id, idempotency: command, if_match: version):
    pass


@proposed.post(
    "/v1/assessment-sessions",
    response_model=dto.AssessmentSession,
    status_code=201,
    responses=errors,
)
def session(body: dto.SessionCommand, idempotency: command):
    pass


@proposed.post(
    "/v1/assessment-sessions/{session_id}/submit",
    response_model=dto.AssessmentSession,
    responses=errors,
)
def submit(session_id: object_id, idempotency: command, if_match: version):
    pass


@proposed.post(
    "/v1/assessment-sessions/{session_id}/review",
    response_model=dto.GradeDecision,
    responses=errors,
)
def review(session_id: object_id, body: dto.ReviewCommand, idempotency: command, if_match: version):
    pass


@proposed.post("/v1/hiring-needs", response_model=dto.HiringNeed, status_code=201, responses=errors)
def need(body: dto.HiringNeedCommand, idempotency: command):
    pass


@proposed.get(
    "/v1/hiring-needs/{need_id}/matches", response_model=list[dto.Match], responses=errors
)
def matches(need_id: object_id):
    pass


@proposed.post("/v1/invitations", response_model=dto.Invitation, status_code=201, responses=errors)
def invitation(body: dto.InvitationCommand, idempotency: command):
    pass


@proposed.post(
    "/v1/invitations/{invitation_id}/accept", response_model=dto.Invitation, responses=errors
)
def accept(
    invitation_id: object_id,
    body: dto.InvitationAcceptanceCommand,
    idempotency: command,
    if_match: version,
):
    pass


@proposed.get(
    "/v1/candidates/{candidate_id}/contacts", response_model=dto.ContactView, responses=errors
)
def contacts(candidate_id: object_id, organization_id: UUID):
    pass


@proposed.post("/v1/ats-exports", response_model=dto.ExportJob, status_code=202, responses=errors)
def export(body: dto.ExportCommand, idempotency: command):
    pass


write(root / "first-scenario.proposed.openapi.json", proposed.openapi())
write(root / "event-envelope.schema.json", EventEnvelope.model_json_schema())
