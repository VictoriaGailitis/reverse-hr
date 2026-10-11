"""Private imports, candidate-confirmed declarations, permission-checked PDF exports."""

import hashlib
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, delete, func, select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.achievement_contracts import ResumeAchievement
from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.resume_contracts import (
    ExtractedPDF,
    PDFData,
    ResumeConfirmation,
    ResumeFields,
    ResumePublication,
)
from reverse_hr.services.candidate.domain.candidate import (
    CandidateBase,
    CandidateProfile,
    specialization_choices,
    subject_lock,
)
from reverse_hr.services.candidate.domain.candidate_grades import current_grade
from reverse_hr.services.candidate.domain.candidate_market import (
    Contacts,
    Publication,
    emit_profile,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.blob_storage import FileBlobStore, object_key
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.storage_errors import BlobUnavailable

MAX_SIZE = 2 * 1024 * 1024


class ResumeImport(CandidateBase):
    __tablename__ = "candidate_resume_imports"
    __table_args__ = (UniqueConstraint("candidate_id", "digest"),)
    import_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    size: Mapped[int]
    manifest: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(24))
    version: Mapped[int]
    attempts: Mapped[int]
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(32))
    extraction: Mapped[dict | None] = mapped_column(JSON)
    proposal: Mapped[dict | None] = mapped_column(JSON)


class Resume(CandidateBase):
    __tablename__ = "candidate_resumes"
    candidate_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    fields: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int]
    published: Mapped[bool]
    consent_id: Mapped[str | None] = mapped_column(String(36))


class ResumeStoreIdentity(CandidateBase):
    __tablename__ = "candidate_resume_store"
    name: Mapped[str] = mapped_column(String(16), primary_key=True)
    identity: Mapped[str] = mapped_column(String(36))


class ImportView(Contract):
    import_id: UUID
    status: Literal["pending", "processing", "review_ready", "confirmed", "failed"]
    digest: str
    size: int
    version: int
    attempts: int
    error: str | None
    extraction: ExtractedPDF | None
    requires_confirmation: bool
    proposal: ResumeFields | None


class ResumeView(Contract):
    fields: ResumeFields
    version: int
    published: bool
    consent_id: UUID | None


router = APIRouter(prefix="/v1/candidates", tags=["resume-pdf"])


def configure(engine, settings):
    engine.resume_antivirus_required = getattr(settings, "resume_antivirus_required", True)
    engine.resume_store = (
        FileBlobStore(settings.resume_storage_root) if settings.resume_storage_root else None
    )


def storage(session):
    store = getattr(session.get_bind(), "resume_store", None)
    if store is None:
        raise HTTPException(503)
    identity = session.get(ResumeStoreIdentity, "primary")
    if identity and identity.identity != store.identity:
        raise HTTPException(503)
    if identity is None:
        session.add(ResumeStoreIdentity(name="primary", identity=store.identity))
        session.flush()
    return store


def guard(request, session, subject):
    subject_lock(session, subject)
    request.app.state.processing_access.check(UUID(str(subject)))


def import_guard(request, actor, session, import_id):
    actor.require("candidate")
    guard(request, session, actor.subject)
    row = session.get(ResumeImport, str(import_id))
    if not row or row.candidate_id != str(actor.subject):
        raise HTTPException(404)
    return row


def import_view(row):
    if row is None:
        raise HTTPException(404)
    return ImportView(
        import_id=row.import_id,
        status=row.status,
        digest=row.digest,
        size=row.size,
        version=row.version,
        attempts=row.attempts,
        error=row.error,
        extraction=row.extraction,
        requires_confirmation=row.status != "confirmed",
        proposal=row.proposal,
    ).model_dump(mode="json")


def resume_view(row, session):
    if row is None:
        raise HTTPException(404)
    contacts = session.get(Contacts, row.candidate_id)
    profile = session.get(CandidateProfile, row.candidate_id)
    fields = dict(row.fields) | {
        "contacts": ({"email": contacts.email, "phone": contacts.phone} if contacts else None),
        "additional_specializations": [
            item
            for item in (profile.additional_specializations if profile else [])
            if item["specialization"].casefold() != row.fields["specialization"].casefold()
        ],
    }
    return ResumeView(
        fields=fields, version=row.version, published=row.published, consent_id=row.consent_id
    ).model_dump(mode="json")


@router.post(
    "/me/resume-imports",
    response_model=ImportView,
    status_code=201,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}},
        }
    },
)
async def upload(request: Request, actor: Actor, idempotency: CommandKey):
    actor.require("candidate")
    if request.headers.get("content-type", "").split(";")[0] != "application/pdf":
        raise HTTPException(415)
    raw = bytearray()
    async for part in request.stream():
        if len(raw) + len(part) > MAX_SIZE:
            raise HTTPException(413)
        raw.extend(part)
    raw = bytes(raw)
    if not raw.startswith(b"%PDF-") or len(raw) < 12:
        raise HTTPException(422)
    digest = hashlib.sha256(raw).hexdigest()

    def admission(session):
        guard(request, session, actor.subject)
        storage(session)

    def change(session):
        existing = session.scalar(
            select(ResumeImport).where(
                ResumeImport.candidate_id == str(actor.subject), ResumeImport.digest == digest
            )
        )
        if existing:
            return {"import_id": existing.import_id}
        if session.scalar(
            select(ResumeImport.import_id).where(
                ResumeImport.candidate_id == str(actor.subject), ResumeImport.status == "pending"
            )
        ):
            raise HTTPException(409)
        if (
            session.scalar(
                select(func.count())
                .select_from(ResumeImport)
                .where(ResumeImport.candidate_id == str(actor.subject))
            )
            >= 20
        ):
            raise HTTPException(409, "Resume import limit reached")
        row = ResumeImport(
            import_id=str(uuid4()),
            candidate_id=str(actor.subject),
            digest=digest,
            size=len(raw),
            manifest=[],
            status="pending",
            version=1,
            attempts=0,
            next_at=datetime.now(UTC),
        )
        store = storage(session)
        manifest = []
        try:
            for number, start in enumerate(range(0, len(raw), 262144)):
                part = raw[start : start + 262144]
                checksum = hashlib.sha256(part).hexdigest()
                key = object_key(actor.subject, row.import_id, number, checksum)
                store.put(key, part, checksum)
                manifest.append(dict(key=key, size=len(part), digest=checksum))
        except BlobUnavailable as exc:
            raise HTTPException(503) from exc
        row.manifest = manifest
        session.add(row)
        return {"import_id": row.import_id}

    # The blocking store/transaction operates outside the async request loop.
    from starlette.concurrency import run_in_threadpool

    return await run_in_threadpool(
        execute,
        request.app.state.engine,
        actor.subject,
        "resume_upload",
        idempotency,
        dict(digest=digest, size=len(raw)),
        change,
        201,
        guard=admission,
        present=lambda session, value: import_view(session.get(ResumeImport, value["import_id"])),
    )


@router.get("/me/resume-imports", response_model=list[ImportView])
def imports(request: Request, actor: Actor, after: UUID | None = None):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        guard(request, session, actor.subject)
        query = select(ResumeImport).where(ResumeImport.candidate_id == str(actor.subject))
        if after:
            query = query.where(ResumeImport.import_id > str(after))
        return [
            import_view(row)
            for row in session.scalars(query.order_by(ResumeImport.import_id).limit(20))
        ]


@router.get("/me/resume-imports/{import_id}", response_model=ImportView)
def get_import(request: Request, actor: Actor, import_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        return import_view(import_guard(request, actor, session, import_id))


@router.get(
    "/me/resume-imports/{import_id}/source.pdf",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def original(request: Request, actor: Actor, import_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = import_guard(request, actor, session, import_id)
        if row.status not in {"review_ready", "confirmed"}:
            raise HTTPException(409)
        raw = read_source(session, row)
        guard(request, session, actor.subject)
        return pdf_response(raw, "original-resume.pdf")


def read_source(session, row):
    store = storage(session)
    try:
        if (
            not 1 <= row.size <= MAX_SIZE
            or not 1 <= len(row.manifest) <= 8
            or sum(p["size"] for p in row.manifest) != row.size
        ):
            raise ValueError("Invalid manifest")
        for number, part in enumerate(row.manifest):
            if (
                part["key"] != object_key(row.candidate_id, row.import_id, number, part["digest"])
                or not 1 <= part["size"] <= 262144
            ):
                raise ValueError("Unbound blob")
        raw = b"".join(store.read(p["key"], p["size"], p["digest"]) for p in row.manifest)
    except (BlobUnavailable, ValueError, KeyError, OSError) as exc:
        raise HTTPException(503) from exc
    if len(raw) != row.size or hashlib.sha256(raw).hexdigest() != row.digest:
        raise HTTPException(503)
    return raw


def save_fields(session, request, subject, body):
    profile = session.get(CandidateProfile, str(subject))
    if (profile.version if profile else 0) != body.profile_version:
        raise HTTPException(409)
    fields = ResumeFields.model_validate(body.model_dump(exclude={"profile_version"})).model_dump(
        mode="json"
    )
    if profile is None:
        profile = CandidateProfile(
            candidate_id=str(subject),
            version=1,
            display_name=body.display_name,
            specialization=body.specialization,
            declared_grade=body.declared_grade.value,
            additional_specializations=[
                item.model_dump(mode="json") for item in body.additional_specializations
            ],
        )
        session.add(profile)
    else:
        profile.display_name, profile.specialization, profile.declared_grade = (
            body.display_name,
            body.specialization,
            body.declared_grade.value,
        )
        if "additional_specializations" in body.model_fields_set:
            profile.additional_specializations = [
                item.model_dump(mode="json") for item in body.additional_specializations
            ]
        profile.additional_specializations = [
            item
            for item in (profile.additional_specializations or [])
            if item["specialization"].casefold() != body.specialization.strip().casefold()
        ]
        profile.version += 1
    publication = session.get(Publication, str(subject))
    if publication is None:
        publication = Publication(
            candidate_id=str(subject), published=False, declared_skills=body.declared_skills
        )
        session.add(publication)
    else:
        publication.declared_skills = body.declared_skills
    if body.contacts:
        contacts = session.get(Contacts, str(subject))
        if contacts is None:
            contacts = Contacts(candidate_id=str(subject), version=1)
            session.add(contacts)
        else:
            contacts.version += 1
        contacts.email, contacts.phone = body.contacts.email, body.contacts.phone
    # Contacts have their own owner and live representation. No duplicate in resume fields.
    fields["contacts"] = None
    row = session.get(Resume, str(subject))
    if row is None:
        row = Resume(candidate_id=str(subject), fields=fields, version=1, published=False)
        session.add(row)
    else:
        row.fields, row.version = fields, row.version + 1
        row.published, row.consent_id = False, None
    emit_profile(session, profile, request.state.trace_id)
    return row


@router.post("/me/resume-imports/{import_id}/confirm", response_model=ResumeView)
def confirm(
    request: Request,
    actor: Actor,
    import_id: UUID,
    body: ResumeConfirmation,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def admission(session):
        import_guard(request, actor, session, import_id)

    def change(session):
        row = session.get(ResumeImport, str(import_id))
        if row.status != "review_ready" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        save_fields(session, request, actor.subject, body)
        row.status, row.version = "confirmed", row.version + 1
        # Keep extraction only privately until document removal/Privacy erasure.
        return {"candidate_id": str(actor.subject)}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"resume_confirm:{import_id}",
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        guard=admission,
        present=lambda session, _: resume_view(session.get(Resume, str(actor.subject)), session),
    )


@router.put("/me/resume", response_model=ResumeView)
def edit(
    request: Request,
    actor: Actor,
    body: ResumeConfirmation,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")

    def admission(session):
        guard(request, session, actor.subject)

    def change(session):
        row = session.get(Resume, str(actor.subject))
        if (row.version if row else 1) != int(if_match.strip('"')):
            raise HTTPException(409)
        save_fields(session, request, actor.subject, body)
        return {"candidate_id": str(actor.subject)}

    return execute(
        request.app.state.engine,
        actor.subject,
        "resume_edit",
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        guard=admission,
        present=lambda session, _: resume_view(session.get(Resume, str(actor.subject)), session),
    )


@router.get("/me/resume", response_model=ResumeView)
def get_resume(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        guard(request, session, actor.subject)
        return resume_view(session.get(Resume, str(actor.subject)), session)


@router.put("/me/resume/publication", response_model=ResumeView)
def publication(
    request: Request,
    actor: Actor,
    body: ResumePublication,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")

    def admission(session):
        guard(request, session, actor.subject)
        if body.published:
            request.app.state.market_access.require(
                "privacy",
                "purpose-permission",
                candidate_id=actor.subject,
                consent_id=body.consent_id,
                consent_purpose="resume_publication",
            )

    def change(session):
        row = session.get(Resume, str(actor.subject))
        if row is None:
            raise HTTPException(404)
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        row.published, row.consent_id, row.version = (
            body.published,
            str(body.consent_id) if body.consent_id else None,
            row.version + 1,
        )
        return {"candidate_id": str(actor.subject)}

    return execute(
        request.app.state.engine,
        actor.subject,
        "resume_publication",
        idempotency,
        dict(body=body.model_dump(mode="json"), version=if_match),
        change,
        guard=admission,
        present=lambda session, _: resume_view(session.get(Resume, str(actor.subject)), session),
    )


@router.post("/me/resume-imports/{import_id}/retry", response_model=ImportView)
def retry(
    request: Request,
    actor: Actor,
    import_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def change(session):
        row = session.get(ResumeImport, str(import_id))
        if row.status != "failed" or row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        storage(session)
        row.status, row.version, row.error, row.attempts, row.next_at = (
            "pending",
            row.version + 1,
            None,
            0,
            datetime.now(UTC),
        )
        return {"import_id": row.import_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"resume_retry:{import_id}",
        idempotency,
        dict(version=if_match),
        change,
        guard=lambda session: import_guard(request, actor, session, import_id),
        present=lambda session, value: import_view(session.get(ResumeImport, value["import_id"])),
    )


def redact(value, name, contacts):
    text = unicodedata.normalize("NFKC", value)
    text = "".join(c for c in text if unicodedata.category(c) != "Cf")
    text = re.sub(r"(?i)(\[|\()\s*(at|собака)\s*(\]|\))", "@", text)
    text = re.sub(r"(?i)(\[|\()\s*dot\s*(\]|\))", ".", text)
    text = re.sub(r"(?i)\s+at\s+", "@", text)
    text = re.sub(r"(?i)\s+dot\s+", ".", text)
    text = re.sub(r"[^\s@]+\s*@\s*[^\s@]+", "[contact removed]", text)
    text = re.sub(r"(?i)(?:https?://|www\.|t\.me/|mailto:|tel:)[^\s]+", "[link removed]", text)
    text = re.sub(
        r"(?i)\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|ru|me|dev|рф)(?:/[^\s]*)?",
        "[link removed]",
        text,
    )
    text = re.sub(
        r"\+?\d[\d\s().-]{5,}\d",
        lambda m: "[phone removed]" if sum(c.isdigit() for c in m[0]) >= 7 else m[0],
        text,
    )
    for token in [
        name,
        *name.split(),
        contacts.email if contacts else "",
        contacts.phone if contacts and contacts.phone else "",
    ]:
        if len(token.strip()) >= 2:
            text = re.sub(re.escape(token), "[identity removed]", text, flags=re.I)
    return text


def pdf_response(raw, name):
    return Response(
        raw,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


def export_guard(request, actor, session, candidate, variant, organization, invitation):
    for subject in sorted({str(candidate), str(actor.subject)}):
        guard(request, session, subject)
    row = session.get(Resume, str(candidate))
    profile = session.get(CandidateProfile, str(candidate))
    if row is None or profile is None:
        raise HTTPException(404)
    if candidate == actor.subject:
        actor.require("candidate")
    else:
        actor.require("employer")
        if not organization:
            raise HTTPException(422)
        request.app.state.market_access.require(
            "employer",
            "membership",
            candidate_id=actor.subject,
            actor_id=actor.subject,
            organization_id=organization,
        )
        publication = session.get(Publication, str(candidate))
        if (
            not row.published
            or not row.consent_id
            or not publication
            or not publication.published
            or not publication.consent_id
        ):
            raise HTTPException(409)
        for consent, purpose in (
            (row.consent_id, "resume_publication"),
            (publication.consent_id, "profile_publication"),
        ):
            request.app.state.market_access.require(
                "privacy",
                "purpose-permission",
                candidate_id=candidate,
                consent_id=UUID(consent),
                consent_purpose=purpose,
            )
        if variant == "full":
            if not invitation:
                raise HTTPException(422)
            request.app.state.market_access.require(
                "privacy",
                "contact-permission",
                candidate_id=candidate,
                organization_id=organization,
                invitation_id=invitation,
            )
    return row, profile


@router.get(
    "/{candidate_id}/resume.pdf",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def pdf(
    request: Request,
    actor: Actor,
    candidate_id: UUID,
    variant: Literal["full", "anonymous"] = "anonymous",
    organization_id: UUID | None = None,
    invitation_id: UUID | None = None,
):
    def achievements():
        if not request.app.state.settings.resume_achievements_enabled:
            return []
        receipt = request.app.state.exchange_access.call(
            "achievements",
            "resume",
            candidate_id,
            uuid4(),
            mode=request.app.state.settings.deployment_mode,
        )
        if set(receipt) != {"achievements"}:
            raise HTTPException(503)
        return [ResumeAchievement.model_validate(value) for value in receipt["achievements"]]

    evidence = achievements()
    with Session(request.app.state.engine) as session, session.begin():
        row, profile = export_guard(
            request, actor, session, candidate_id, variant, organization_id, invitation_id
        )
        fields = ResumeFields.model_validate(row.fields)
        contacts = session.get(Contacts, str(candidate_id))

        def clean(value):
            return (
                redact(value, profile.display_name, contacts) if variant == "anonymous" else value
            )

        safe_evidence = [
            item.model_copy(
                update={
                    "event": clean(item.event),
                    "discipline": clean(item.discipline),
                    "source_name": clean(item.source_name),
                }
            )
            for item in evidence
        ]
        data = PDFData(
            achievements=safe_evidence,
            variant=variant,
            name=profile.display_name
            if variant == "full"
            else "Candidate " + hashlib.sha256(str(candidate_id).encode()).hexdigest()[:12],
            specializations=[
                dict(
                    specialization=clean(item["specialization"])[:100],
                    declared_grade=item["declared_grade"],
                    confirmed_grade=current_grade(session, candidate_id, item["specialization"]),
                )
                for item in specialization_choices(profile)
            ],
            specialization=clean(profile.specialization)[:100],
            declared_grade=profile.declared_grade,
            confirmed_grade=current_grade(session, candidate_id, profile.specialization),
            declared_skills=[clean(v) for v in fields.declared_skills],
            summary=clean(fields.summary)[:2000],
            experience=[clean(v)[:1000] for v in fields.experience],
            education=[clean(v)[:1000] for v in fields.education],
            email=contacts.email if contacts and variant == "full" else None,
            phone=contacts.phone if contacts and variant == "full" else None,
        )
        snapshot = (
            row.version,
            profile.version,
            contacts.email if contacts else None,
            contacts.phone if contacts else None,
        )

    def hiring_permission():
        if variant == "full" and candidate_id != actor.subject:
            request.app.state.market_access.require(
                "hiring",
                "resume-permission",
                candidate_id=candidate_id,
                actor_id=actor.subject,
                organization_id=organization_id,
                invitation_id=invitation_id,
            )

    # Hiring's contacts path acquires Hiring then Candidate. Never call Hiring
    # while holding Candidate: concurrent contacts/PDF downloads would deadlock.
    hiring_permission()
    raw = request.app.state.resume_guest.render(data)
    if achievements() != evidence:
        raise HTTPException(409, "Achievement evidence changed during PDF generation")
    hiring_permission()
    with Session(request.app.state.engine) as session, session.begin():
        row, profile = export_guard(
            request, actor, session, candidate_id, variant, organization_id, invitation_id
        )
        contacts = session.get(Contacts, str(candidate_id))
        current = (
            row.version,
            profile.version,
            contacts.email if contacts else None,
            contacts.phone if contacts else None,
        )
        if snapshot != current:
            raise HTTPException(409)
        from reverse_hr.protocols.audit_access import record_disclosure

        record_disclosure(
            session,
            request,
            "resume_pdf",
            candidate_id,
            actor.subject,
            candidate_id,
            organization_id,
        )
        return pdf_response(raw, "resume.pdf")


def proposed(text):
    """Conservative section recognition; every extracted declaration requires review."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    sections = {
        "summary": [],
        "experience": [],
        "education": [],
        "declared_skills": [],
        "specialization": [],
    }
    aliases = {
        "опыт": "experience",
        "опыт работы": "experience",
        "experience": "experience",
        "work experience": "experience",
        "employment": "experience",
        "образование": "education",
        "education": "education",
        "навыки": "declared_skills",
        "skills": "declared_skills",
        "technologies": "declared_skills",
        "о себе": "summary",
        "summary": "summary",
        "about": "summary",
        "специализация": "specialization",
        "specialization": "specialization",
        "role": "specialization",
        "роль": "specialization",
    }
    section = "summary"
    for line in lines[1:]:
        heading, separator, rest = line.partition(":")
        key = aliases.get(heading.casefold().strip())
        if key:
            section = key
            if separator and rest.strip():
                sections[section].append(rest.strip())
        else:
            sections[section].append(line)
    skills = sorted(
        {
            value.strip().casefold()
            for line in sections["declared_skills"]
            for value in re.split(r"[,;•]", line)
            if 1 <= len(value.strip()) <= 64
        }
    )[:50]
    email = re.search(r"[^\s@]+@[^\s@]+\.[^\s@]+", text)
    phone = re.search(r"\+?\d[\d ()-]{6,}\d", text)
    return ResumeFields(
        display_name=lines[0][:100] if lines else "Candidate",
        specialization=" ".join(sections["specialization"])[:100] or "unconfirmed",
        declared_grade="junior",
        declared_skills=skills,
        summary="\n".join(sections["summary"])[:2000],
        experience=[line[:1000] for line in sections["experience"][:20]],
        education=[line[:1000] for line in sections["education"][:20]],
        contacts={"email": email[0], "phone": phone[0][:30] if phone else None} if email else None,
    ).model_dump(mode="json")


def run_import_one(engine, processing, guest, scanner, *, now=None):
    now = now or datetime.now(UTC)
    due = (ResumeImport.status.in_(["pending", "processing"])) & (ResumeImport.next_at <= now)
    with Session(engine) as session:
        row = session.scalar(
            select(ResumeImport)
            .where(due)
            .order_by(ResumeImport.next_at, ResumeImport.import_id)
            .limit(1)
        )
        if row is None:
            return False
        import_id, candidate = row.import_id, row.candidate_id
    error, report, lease = None, None, None
    try:
        with Session(engine) as session, session.begin():
            subject_lock(session, candidate)
            row = session.scalar(
                select(ResumeImport)
                .where(ResumeImport.import_id == import_id, due)
                .with_for_update()
            )
            if row is None:
                return True
            row.status, row.version = "processing", row.version + 1
            row.next_at = now + timedelta(seconds=90)
            lease = row.version
            try:
                processing.check(UUID(candidate))
                raw = read_source(session, row)
            except HTTPException as exc:
                error = "processing_unavailable" if exc.status_code >= 500 else "permission_revoked"
        if error is None:
            if scanner is None and getattr(engine, "resume_antivirus_required", True):
                raise HTTPException(503)
            if scanner:
                scanner.scan(raw)
            report = guest.extract(raw)
            proposal = proposed(report.text)
    except HTTPException as exc:
        error = (
            "invalid_pdf"
            if exc.status_code in {413, 415, 422}
            else "processing_unavailable"
            if exc.status_code >= 500
            else "permission_revoked"
        )
    except Exception:
        error = "processing_unavailable"
    try:
        with Session(engine) as session, session.begin():
            state = subject_lock(session, candidate, allow_blocked=True)
            row = session.scalar(
                select(ResumeImport).where(ResumeImport.import_id == import_id).with_for_update()
            )
            # An expired lease, erasure or another completed worker cannot be resurrected.
            if state.blocked or not row or row.status != "processing" or row.version != lease:
                return True
            try:
                processing.check(UUID(candidate))
            except HTTPException as exc:
                error = "permission_revoked" if exc.status_code < 500 else "processing_unavailable"
            row.attempts += 1
            row.version += 1
            if error:
                row.error = error
                if error == "processing_unavailable" and row.attempts < 8:
                    row.status = "pending"
                    row.next_at = now + timedelta(seconds=min(3600, 10 * 2**row.attempts))
                else:
                    row.status = "failed"
                return True
            row.status, row.error, row.extraction, row.proposal = (
                "review_ready",
                None,
                report.model_dump(mode="json"),
                proposal,
            )
        return True
    except (IntegrityError, OperationalError):
        return False


def purge(session, subject):
    store = getattr(session.get_bind(), "resume_store", None)
    imports = list(
        session.scalars(
            select(ResumeImport.import_id).where(ResumeImport.candidate_id == str(subject))
        )
    )
    if imports and store is None:
        raise HTTPException(503)
    if store:
        storage(session)
        try:
            store.purge_subject(subject)
        except BlobUnavailable as exc:
            raise HTTPException(503) from exc
    session.execute(delete(ResumeImport).where(ResumeImport.candidate_id == str(subject)))
    session.execute(delete(Resume).where(Resume.candidate_id == str(subject)))


class ImportRemoved(Contract):
    import_id: UUID
    deleted: Literal[True] = True


@router.delete("/me/resume-imports/{import_id}", response_model=ImportRemoved)
def remove_import(
    request: Request,
    actor: Actor,
    import_id: UUID,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("candidate")

    def admission(session):
        guard(request, session, actor.subject)
        row = session.get(ResumeImport, str(import_id))
        if row is not None and row.candidate_id != str(actor.subject):
            raise HTTPException(404)

    def change(session):
        row = session.get(ResumeImport, str(import_id))
        if row is None:
            raise HTTPException(404)
        if row.version != int(if_match.strip('"')):
            raise HTTPException(409)
        try:
            storage(session).purge_recording(actor.subject, import_id)
        except BlobUnavailable as exc:
            raise HTTPException(503) from exc
        session.delete(row)
        return ImportRemoved(import_id=import_id).model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"resume_remove:{import_id}",
        idempotency,
        {"version": if_match},
        change,
        guard=admission,
    )
