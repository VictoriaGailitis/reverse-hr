"""Durable immutable subject archives, advanced one signed owner page at a time."""

import hashlib
from datetime import UTC, datetime
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import RootModel
from sqlalchemy import JSON, DateTime, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.coordination.rights_export import encode, make_cursor, page, read_cursor
from reverse_hr.platform.settings import SERVICES
from reverse_hr.services.privacy.domain.privacy import PrivacyBase
from reverse_hr.services.privacy.domain.privacy_requests import audit, guard
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.signing import sign, verify


class PrivacyArchive(PrivacyBase):
    __tablename__ = "privacy_archives"
    archive_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    revision: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))
    manifest: Mapped[dict] = mapped_column(JSON)
    position: Mapped[int]
    cursor: Mapped[str | None] = mapped_column(String(16384))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ArchivePage(PrivacyBase):
    __tablename__ = "privacy_archive_pages"
    archive_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    owner: Mapped[str] = mapped_column(String(50))
    data: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    previous_digest: Mapped[str] = mapped_column(String(64))


router = APIRouter(prefix="/v1/data-subject-requests", tags=["subject-archives"])


def scrub(session, subject=None, request_id=None):
    query = select(PrivacyArchive.archive_id)
    query = (
        query.where(PrivacyArchive.candidate_id == str(subject))
        if subject
        else query.where(PrivacyArchive.request_id == str(request_id))
    )
    ids = list(session.scalars(query))
    if ids:
        session.execute(delete(ArchivePage).where(ArchivePage.archive_id.in_(ids)))
        session.execute(delete(PrivacyArchive).where(PrivacyArchive.archive_id.in_(ids)))


def load(request, session, actor, request_id, archive_id):
    authorization = guard(request, session, actor, request_id)
    archive = session.get(PrivacyArchive, str(archive_id))
    if (
        not archive
        or archive.request_id != str(request_id)
        or archive.candidate_id != str(actor.subject)
    ):
        raise HTTPException(404)
    if (
        authorization.kind != "access"
        or authorization.status not in {"approved", "completed"}
        or authorization.version != archive.revision
    ):
        raise HTTPException(409, "Archive authorization changed")
    return authorization, archive


def verify_manifest(session, archive, signatures):
    if archive.status != "ready":
        return
    if (
        archive.manifest.get("archive_id") != archive.archive_id
        or archive.manifest.get("request_id") != archive.request_id
        or archive.manifest.get("subject") != archive.candidate_id
        or archive.manifest.get("capture_revision")
        != archive.revision - (1 if archive.manifest.get("complete") else 0)
    ):
        raise HTTPException(503, "Archive manifest recipient binding failure")
    expected = archive.manifest.get("digest")
    manifest = {k: v for k, v in archive.manifest.items() if k not in {"digest", "signature"}}
    if hashlib.sha256(encode(manifest)).hexdigest() != expected:
        raise HTTPException(503, "Archive manifest integrity failure")
    signed = manifest | {"digest": expected}
    try:
        verify(
            signatures,
            "privacy",
            archive.manifest["signature"],
            b"reverse-hr.subject-archive-manifest.v1\0",
            RootModel[dict](signed),
        )
    except Exception as exc:
        raise HTTPException(503, "Archive manifest signature failure") from exc
    head, count = "0" * 64, 0
    query = (
        select(
            ArchivePage.number, ArchivePage.owner, ArchivePage.digest, ArchivePage.previous_digest
        )
        .where(ArchivePage.archive_id == archive.archive_id)
        .order_by(ArchivePage.number)
        .execution_options(yield_per=100)
    )
    for number, owner, digest, previous in session.execute(query):
        if number != count or previous != head or owner not in manifest["owners"]:
            raise HTTPException(503, "Archive chain integrity failure")
        head = hashlib.sha256(
            encode(dict(previous_digest=previous, number=number, owner=owner, digest=digest))
        ).hexdigest()
        count += 1
    if count != manifest["page_count"] or head != manifest["chain_head"]:
        raise HTTPException(503, "Archive chain integrity failure")


def view(archive):
    return dict(
        archive_id=archive.archive_id,
        request_id=archive.request_id,
        status=archive.status,
        version=archive.version,
        manifest=archive.manifest,
    )


@router.post("/{request_id}/archives", status_code=201)
def create(request: Request, actor: Actor, request_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row = guard(request, session, actor, request_id)
        if row.kind != "access" or row.status != "approved":
            raise HTTPException(409)
        existing = session.scalar(
            select(PrivacyArchive).where(
                PrivacyArchive.request_id == str(request_id),
                PrivacyArchive.status.in_(["building", "ready"]),
            )
        )
        if existing:
            return view(existing)
        owners = [row.domain] if row.domain else list(SERVICES)
        identity_enabled = getattr(request.app.state.settings, "identity_export_enabled", False)
        capabilities = {
            owner: (
                "external_identity_unavailable"
                if owner == "identity" and not identity_enabled
                else "paged"
            )
            for owner in owners
        }
        archive = PrivacyArchive(
            archive_id=str(uuid4()),
            request_id=str(request_id),
            candidate_id=str(actor.subject),
            revision=row.version,
            status="building",
            manifest=dict(
                format="subject-archive-v1",
                capabilities=capabilities,
                owners=[x for x in owners if capabilities[x] == "paged"],
                page_count=0,
                chain_head="0" * 64,
                sources={},
                complete=False,
            ),
            position=0,
            cursor=None,
            version=1,
            created_at=datetime.now(UTC),
        )
        session.add(archive)
        return view(archive)


@router.post("/{request_id}/archives/{archive_id}/advance")
def advance(request: Request, actor: Actor, request_id: UUID, archive_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        row, archive = load(request, session, actor, request_id, archive_id)
        if archive.status != "building":
            return view(archive)
        owners = archive.manifest["owners"]
        version, revision, position, cursor = (
            archive.version,
            archive.revision,
            archive.position,
            archive.cursor,
        )
        owner = owners[position] if position < len(owners) else None
        if owner == "privacy":
            captured = page(
                session,
                owner,
                actor.subject,
                request_id,
                revision,
                request.app.state.rights_access.signatures,
                cursor,
            )
        else:
            captured = None
    if owner and captured is None:
        captured = request.app.state.rights_access.call(
            owner, "export-page", actor.subject, request_id, revision, cursor=cursor
        )
    with Session(request.app.state.engine) as session, session.begin():
        row, archive = load(request, session, actor, request_id, archive_id)
        if archive.version != version:
            raise HTTPException(409, "Archive was advanced concurrently; read current progress")
        manifest = dict(archive.manifest)
        if captured is not None:
            if (
                set(captured) != {"source_digest", "records", "next_cursor", "complete"}
                or len(encode(captured)) > 65536
            ):
                raise HTTPException(503, "Malformed owner page")
            number = manifest["page_count"]
            previous = manifest["chain_head"]
            hashed = hashlib.sha256(encode(captured)).hexdigest()
            session.add(
                ArchivePage(
                    archive_id=str(archive_id),
                    number=number,
                    owner=owner,
                    data=captured,
                    digest=hashed,
                    previous_digest=previous,
                )
            )
            manifest["page_count"] = number + 1
            manifest["chain_head"] = hashlib.sha256(
                encode(dict(previous_digest=previous, number=number, owner=owner, digest=hashed))
            ).hexdigest()
            sources = dict(manifest["sources"])
            if owner in sources and sources[owner] != captured["source_digest"]:
                raise HTTPException(409, "Owner source changed")
            sources[owner] = captured["source_digest"]
            manifest["sources"] = sources
            archive.cursor = captured["next_cursor"]
            if captured["complete"]:
                if archive.cursor is not None:
                    raise HTTPException(503)
                archive.position += 1
        archive.version += 1
        if archive.position == len(owners):
            manifest["complete"] = all(
                value == "paged" for value in manifest["capabilities"].values()
            )
            manifest["archive_id"] = str(archive_id)
            manifest["request_id"] = str(request_id)
            manifest["subject"] = str(actor.subject)
            manifest["capture_revision"] = revision
            manifest["digest"] = hashlib.sha256(encode(manifest)).hexdigest()
            manifest["signature"] = sign(
                request.app.state.rights_access.signatures,
                b"reverse-hr.subject-archive-manifest.v1\0",
                RootModel[dict](manifest),
            )
            archive.status = "ready"
            if manifest["complete"]:
                row.status, row.version, row.completed_at = (
                    "completed",
                    row.version + 1,
                    datetime.now(UTC),
                )
                archive.revision = row.version
                audit(
                    session,
                    row,
                    actor.subject,
                    "archive_completed",
                    archive_id=str(archive_id),
                    manifest_digest=manifest["digest"],
                )
        archive.manifest = manifest
        return view(archive)


@router.get("/{request_id}/archives/{archive_id}")
def manifest(request: Request, actor: Actor, request_id: UUID, archive_id: UUID):
    from fastapi.responses import JSONResponse

    with Session(request.app.state.engine) as session, session.begin():
        _, archive = load(request, session, actor, request_id, archive_id)
        verify_manifest(session, archive, request.app.state.rights_access.signatures)
        return JSONResponse(view(archive), headers={"Cache-Control": "no-store"})


@router.get("/{request_id}/archives/{archive_id}/pages")
def download(
    request: Request, actor: Actor, request_id: UUID, archive_id: UUID, cursor: str | None = None
):
    from fastapi.responses import JSONResponse

    with Session(request.app.state.engine) as session, session.begin():
        _, archive = load(request, session, actor, request_id, archive_id)
        if archive.status != "ready":
            raise HTTPException(409)
        verify_manifest(session, archive, request.app.state.rights_access.signatures)
        binding = dict(
            owner="privacy",
            subject=str(actor.subject),
            request_id=str(request_id),
            revision=archive.revision,
            archive_id=str(archive_id),
            manifest_digest=archive.manifest["digest"],
        )
        signatures = request.app.state.rights_access.signatures
        position = read_cursor(signatures, "privacy", cursor, binding)["offset"] if cursor else 0
        stored = session.get(ArchivePage, (str(archive_id), position))
        if stored is None:
            if position != 0 or archive.manifest["page_count"]:
                raise HTTPException(404)
            return JSONResponse(
                dict(records=[], next_cursor=None), headers={"Cache-Control": "no-store"}
            )
        if hashlib.sha256(encode(stored.data)).hexdigest() != stored.digest:
            raise HTTPException(503, "Archive integrity failure")
        next_cursor = (
            make_cursor(signatures, "privacy", binding, archive.manifest["digest"], position + 1)
            if position + 1 < archive.manifest["page_count"]
            else None
        )
        return JSONResponse(
            dict(
                number=position,
                owner=stored.owner,
                digest=stored.digest,
                previous_digest=stored.previous_digest,
                data=stored.data,
                next_cursor=next_cursor,
            ),
            headers={"Cache-Control": "no-store"},
        )


@router.post("/{request_id}/archives/{archive_id}/abandon", status_code=204)
def abandon(request: Request, actor: Actor, request_id: UUID, archive_id: UUID):
    from fastapi import Response

    with Session(request.app.state.engine) as session, session.begin():
        _, archive = load(request, session, actor, request_id, archive_id)
        if archive.status != "building":
            raise HTTPException(409, "Completed capture is immutable; withdraw its authorization")
        session.execute(delete(ArchivePage).where(ArchivePage.archive_id == str(archive_id)))
        session.delete(archive)
    return Response(status_code=204)
