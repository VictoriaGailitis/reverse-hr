"""Fixed-origin signed rights export/correction protocol with explicit owner allowlists."""

import base64
import json
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.error import HTTPError
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import Field
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.contracts.core import Contract, ProfileUpdate
from reverse_hr.contracts.test_suites import digest
from reverse_hr.platform.settings import SERVICES
from reverse_hr.protocols.market_access import Signature
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.shared.signing import canonical, fresh, sign, verify

OWNERS = set(SERVICES)
LIMIT = 1024 * 1024


class RightsExchange(Contract):
    requester: str
    operation: Literal["permission", "export", "correct", "export-page"]
    cursor: str | None = Field(default=None, max_length=16384)
    candidate_id: UUID
    request_id: UUID
    revision: int = Field(strict=True, ge=1)
    nonce: UUID
    issued_at: datetime


class RightsReceipt(Contract):
    request_digest: str
    issued_at: datetime
    data: dict


def context(owner, operation, direction):
    return f"reverse-hr.subject-rights.{owner}.{operation}.{direction}.v1\0".encode()


class RightsAccess(ProcessingAccess):
    def call(self, owner, operation, candidate_id, request_id, revision, cursor=None):
        if owner not in OWNERS:
            raise HTTPException(409)
        body = RightsExchange(
            requester=self.settings.service_name,
            operation=operation,
            cursor=cursor,
            candidate_id=candidate_id,
            request_id=request_id,
            revision=revision,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        origin = getattr(
            self.settings,
            {"coding-workspace": "workspace", "code-runner": "code_runner"}.get(owner, owner)
            + "_api_url",
        )
        try:
            raw, signature = self._send(
                "subject-rights/" + operation,
                canonical(body),
                sign(self.signatures, context(owner, operation, "request"), body),
                origin=origin,
                max_bytes=LIMIT,
            )
            if len(raw) > LIMIT:
                raise ValueError("Response limit")
            receipt = RightsReceipt.model_validate_json(raw)
            verify(
                self.signatures, owner, signature, context(owner, operation, "response"), receipt
            )
            if (
                raw != canonical(receipt)
                or not fresh(receipt.issued_at)
                or receipt.request_digest != digest(body)
            ):
                raise ValueError("Unbound receipt")
            return receipt.data
        except HTTPError as exc:
            raise HTTPException(exc.code if exc.code in {401, 403, 404, 409, 422} else 503) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(503) from exc


router = APIRouter(prefix="/internal/v1/subject-rights", tags=["internal-subject-rights"])


def nonce_model(owner):
    if owner == "privacy":
        from reverse_hr.services.privacy.domain.privacy import ProcessingNonce

        return ProcessingNonce
    if owner == "candidate":
        from reverse_hr.services.candidate.domain.candidate_market import CandidateNonce

        return CandidateNonce
    if owner == "hiring":
        from reverse_hr.services.hiring.domain.hiring import HiringNonce

        return HiringNonce
    from reverse_hr.services.achievements.domain.achievements import AchievementNonce

    return AchievementNonce


def rows(session, model, candidate):
    values = list(
        session.scalars(select(model).where(model.candidate_id == str(candidate)).limit(1001))
    )
    if len(values) > 1000:
        raise HTTPException(409, "Paginated archive required; export is not complete")
    return values


def snapshot(session, owner, candidate):
    """Never export another subject's identity, credentials, internal proofs or storage paths."""
    if owner == "candidate":
        from reverse_hr.services.candidate.domain.candidate import CandidateProfile, subject_lock
        from reverse_hr.services.candidate.domain.candidate_grades import CandidateDecision
        from reverse_hr.services.candidate.domain.candidate_market import Contacts, Publication
        from reverse_hr.services.candidate.domain.candidate_resume import (
            Resume,
            ResumeImport,
            read_source,
        )

        subject_lock(session, candidate)
        profile = session.get(CandidateProfile, str(candidate))
        contact = session.get(Contacts, str(candidate))
        publication = session.get(Publication, str(candidate))
        resume = session.get(Resume, str(candidate))
        return dict(
            profile=(
                dict(
                    display_name=profile.display_name,
                    specialization=profile.specialization,
                    declared_grade=profile.declared_grade,
                    additional_specializations=profile.additional_specializations or [],
                    version=profile.version,
                )
                if profile
                else None
            ),
            contacts=dict(email=contact.email, phone=contact.phone) if contact else None,
            publication=dict(
                published=publication.published, declared_skills=publication.declared_skills
            )
            if publication
            else None,
            resume=dict(fields=resume.fields, version=resume.version, published=resume.published)
            if resume
            else None,
            resume_imports=[
                dict(
                    import_id=row.import_id,
                    status=row.status,
                    version=row.version,
                    extraction=row.extraction,
                    proposal=row.proposal,
                    source_pdf_base64=base64.b64encode(read_source(session, row)).decode("ascii")
                    if row.manifest
                    else None,
                )
                for row in rows(session, ResumeImport, candidate)
            ],
            qualifications=[
                dict(
                    decision_id=row.decision_id,
                    session_id=row.session_id,
                    specialization=row.summary["specialization"],
                    target_grade=row.summary["target_grade"],
                    status=row.summary["status"],
                    demo=row.summary["demo"],
                    revision=row.summary["decision_revision"],
                    qualification=row.summary.get("qualification"),
                )
                for row in rows(session, CandidateDecision, candidate)
            ],
        )
    if owner == "achievements":
        from reverse_hr.protocols.market_state import lock
        from reverse_hr.services.achievements.domain.achievements import (
            AchievementHistory,
            AchievementRow,
            AchievementSubject,
            Connection,
            SourceRow,
        )

        lock(session, AchievementSubject, candidate)
        achievements = rows(session, AchievementRow, candidate)
        return dict(
            achievements=[
                dict(
                    achievement_id=row.achievement_id,
                    source_name=session.get(SourceRow, row.source_id).name,
                    result=row.data,
                    status=row.status,
                    published=row.published,
                    demo=row.demo,
                    version=row.version,
                )
                for row in achievements
            ],
            history=[
                dict(
                    achievement_id=row.achievement_id,
                    version=row.version,
                    action=row.action,
                    recorded_at=row.at.isoformat(),
                    snapshot=row.snapshot,
                )
                for row in rows(session, AchievementHistory, candidate)
            ],
            connections=[
                dict(
                    connection_id=row.connection_id,
                    source_id=row.source_id,
                    status=row.status,
                    external_account=row.external_account,
                    version=row.version,
                )
                for row in rows(session, Connection, candidate)
            ],
        )
    if owner == "hiring":
        from reverse_hr.protocols.market_state import lock
        from reverse_hr.services.hiring.domain.hiring import (
            HiringSubject,
            InvitationRevision,
            InvitationRow,
        )
        from reverse_hr.services.hiring.domain.hiring_vacancies import Application

        lock(session, HiringSubject, candidate)
        return dict(
            invitations=[
                dict(
                    invitation_id=row.invitation_id,
                    organization_id=row.organization_id,
                    description=row.spec["description"],
                    salary=row.spec["salary"],
                    status=row.status,
                    version=row.version,
                    expires_at=row.expires_at.isoformat(),
                )
                for row in rows(session, InvitationRow, candidate)
                if row.status != "draft"
            ],
            invitation_history=[
                dict(
                    invitation_id=row.invitation_id,
                    version=row.version,
                    predecessor_id=row.predecessor_id,
                    recorded_at=row.recorded_at.isoformat(),
                    terms={
                        key: value for key, value in row.terms.items() if key != "employer_contact"
                    },
                )
                for row in rows(session, InvitationRevision, candidate)
                if (
                    session.get(InvitationRow, row.invitation_id) is not None
                    and session.get(InvitationRow, row.invitation_id).status != "draft"
                )
            ],
            applications=[
                dict(
                    application_id=row.application_id,
                    organization_id=row.organization_id,
                    vacancy_id=row.vacancy_id,
                    invitation_id=row.invitation_id,
                    status=row.status,
                    version=row.version,
                )
                for row in rows(session, Application, candidate)
            ],
        )
    from reverse_hr.services.privacy.domain.privacy import (
        ConsentRecord,
        ContactGrant,
        subject_lock,
        view,
    )
    from reverse_hr.services.privacy.domain.privacy_requests import RequestHistory, SubjectRequest
    from reverse_hr.services.privacy.domain.privacy_requests import view as request_view

    subject_lock(session, candidate)
    return dict(
        consents=[view(row) for row in rows(session, ConsentRecord, candidate)],
        contact_grants=[
            dict(
                grant_id=row.grant_id,
                invitation_id=row.invitation_id,
                organization_id=row.organization_id,
                status=row.status,
                version=row.version,
            )
            for row in rows(session, ContactGrant, candidate)
        ],
        requests=[request_view(row) for row in rows(session, SubjectRequest, candidate)],
        history=[
            dict(
                request_id=row.request_id,
                version=row.version,
                action=row.action,
                at=row.at.isoformat(),
                details=row.details,
            )
            for row in rows(session, RequestHistory, candidate)
        ],
    )


@router.post("/{operation}", response_model=RightsReceipt)
def exchange(request: Request, body: RightsExchange, operation: str, signature: Signature = None):
    owner = request.app.state.settings.service_name
    if (
        owner not in OWNERS
        or body.requester not in OWNERS
        or operation != body.operation
        or not fresh(body.issued_at)
    ):
        raise HTTPException(401)
    if (operation == "permission" and (owner != "privacy" or body.requester == "privacy")) or (
        operation != "permission" and body.requester != "privacy"
    ):
        raise HTTPException(401)
    signatures = request.app.state.rights_access.signatures
    try:
        verify(signatures, body.requester, signature, context(owner, operation, "request"), body)
    except Exception as exc:
        raise HTTPException(401) from exc
    # Authenticate first; owner authorization comes from Privacy, never from caller input.
    authorization = None
    if operation != "permission":
        authorization = request.app.state.rights_access.call(
            "privacy", "permission", body.candidate_id, body.request_id, body.revision
        )
        if authorization.get("kind") != ("correction" if operation == "correct" else "access"):
            raise HTTPException(403)
    now = datetime.now(UTC)
    from reverse_hr.shared.db import Inbox

    try:
        with Session(request.app.state.engine) as session, session.begin():
            if operation == "export-page" and session.bind.dialect.name == "postgresql":
                session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(
                delete(Inbox).where(
                    Inbox.consumer == "subject-rights.nonce",
                    Inbox.processed_at < now - timedelta(seconds=60),
                )
            )
            session.add(
                Inbox(consumer="subject-rights.nonce", event_id=str(body.nonce), processed_at=now)
            )
            session.flush()
            if operation == "permission":
                from reverse_hr.services.privacy.domain.privacy import subject_lock
                from reverse_hr.services.privacy.domain.privacy_requests import SubjectRequest

                subject_lock(session, body.candidate_id)
                row = session.get(SubjectRequest, str(body.request_id))
                if (
                    not row
                    or row.candidate_id != str(body.candidate_id)
                    or (row.domain is not None and row.domain != body.requester)
                    or row.version != body.revision
                    or row.status not in {"approved", "applying", "completed"}
                ):
                    raise HTTPException(409)
                if row.kind not in {"access", "correction"}:
                    raise HTTPException(403)
                if row.kind == "correction" and row.status != "applying":
                    raise HTTPException(409)
                data = dict(
                    kind=row.kind,
                    changes=row.data.get("proposed_changes"),
                    source_version=row.data.get("source_version"),
                    target=row.data.get("target", "profile"),
                    target_id=row.data.get("target_id"),
                    source_profile_version=row.data.get("source_profile_version"),
                )
            elif operation == "correct":
                if owner not in {"candidate", "achievements", "notification"}:
                    raise HTTPException(409)
                data = correct(session, request, body, authorization)
            elif operation == "export-page":
                from reverse_hr.coordination.rights_export import page

                data = page(
                    session,
                    owner,
                    body.candidate_id,
                    body.request_id,
                    body.revision,
                    signatures,
                    body.cursor,
                )
            else:
                data = snapshot(session, owner, body.candidate_id)
            receipt = RightsReceipt(request_digest=digest(body), issued_at=now, data=data)
            if len(canonical(receipt)) > LIMIT:
                raise HTTPException(409, "Archive exceeds supported response size")
            signature = sign(signatures, context(owner, operation, "response"), receipt)
        return Response(
            canonical(receipt),
            media_type="application/json",
            headers={"X-HR-Signature": signature, "Cache-Control": "no-store"},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc


def correct(session, request, body, permission):
    from reverse_hr.services.candidate.domain.candidate import CandidateProfile, subject_lock
    from reverse_hr.services.candidate.domain.candidate_market import emit_profile
    from reverse_hr.shared.db import IdempotencyRecord

    owner = request.app.state.settings.service_name
    if owner == "candidate":
        subject_lock(session, body.candidate_id)
    else:
        from reverse_hr.protocols.market_state import lock

        if owner == "achievements":
            from reverse_hr.services.achievements.domain.achievements import (
                AchievementSubject as model,
            )
        else:
            from reverse_hr.services.notification.domain.notification import (
                NotificationSubject as model,
            )
        lock(session, model, body.candidate_id)
    existing = session.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.actor_id == str(body.candidate_id),
            IdempotencyRecord.operation == "subject_correction",
            IdempotencyRecord.key == str(body.request_id),
        )
    )
    if existing:
        return json.loads(existing.response)
    if permission.get("target", "profile") == "profile":
        fields = ProfileUpdate.model_validate(permission["changes"])
        profile = session.get(CandidateProfile, str(body.candidate_id))
        if profile is None or profile.version != permission["source_version"]:
            raise HTTPException(409, "Source profile changed; request must be reviewed again")
        profile.display_name, profile.specialization, profile.declared_grade = (
            fields.display_name,
            fields.specialization,
            fields.declared_grade.value,
        )
        if "additional_specializations" in permission["changes"]:
            profile.additional_specializations = [
                item.model_dump(mode="json") for item in fields.additional_specializations
            ]
        else:
            profile.additional_specializations = [
                item
                for item in (profile.additional_specializations or [])
                if item["specialization"].casefold() != fields.specialization.casefold()
            ]
        profile.version += 1
        emit_profile(session, profile, request.state.trace_id)
        result = dict(candidate_id=str(body.candidate_id), profile_version=profile.version)
    else:
        from reverse_hr.coordination.rights_corrections import apply

        result = apply(session, request, body.candidate_id, permission)
    session.add(
        IdempotencyRecord(
            actor_id=str(body.candidate_id),
            operation="subject_correction",
            key=str(body.request_id),
            request_hash=digest(body),
            response=json.dumps(result),
            status_code=200,
            created_at=datetime.now(UTC),
        )
    )
    return result
