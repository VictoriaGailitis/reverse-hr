"""Fixed-origin, fresh, purpose-separated signed recruitment RPC."""

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import Header, HTTPException, Request, Response
from sqlalchemy import delete
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.contracts.core import ContactView
from reverse_hr.contracts.market_contracts import (
    AppealNoticeView,
    CandidateCard,
    CompanyNoticeView,
    MarketReceipt,
    MarketRequest,
    NeedView,
    NoticeView,
)
from reverse_hr.protocols.evaluation_artifact_access import bound
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.shared.signing import canonical, fresh, sign, verify

Signature = Annotated[str | None, Header(alias="X-HR-Signature", max_length=128)]
MAX_BYTES = 16384


def context(owner, purpose, direction):
    return f"reverse-hr.market.{owner}.{purpose}.{direction}.v1\0".encode()


class MarketAccess(ProcessingAccess):
    def fetch(self, owner, purpose, **refs):
        body = MarketRequest(
            requester=self.settings.service_name,
            purpose=purpose,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
            **refs,
        )
        origin = getattr(self.settings, f"{owner}_api_url")
        try:
            raw, signed = self._send(
                "market/" + purpose,
                canonical(body),
                sign(self.signatures, context(owner, purpose, "request"), body),
                origin=origin,
                max_bytes=MAX_BYTES,
            )
            if len(raw) > MAX_BYTES:
                raise ValueError("Oversized receipt")
            receipt = MarketReceipt.model_validate_json(raw)
            verify(self.signatures, owner, signed, context(owner, purpose, "response"), receipt)
            if raw != canonical(receipt) or not bound(body, receipt):
                raise ValueError("Unbound recruitment receipt")
            if receipt.allowed:
                if purpose == "task-catalog":
                    from reverse_hr.contracts.task_discovery import TaskCatalog

                    catalog = TaskCatalog.model_validate(receipt.data)
                    if receipt.revision != 1:
                        raise ValueError("Invalid catalog revision")
                    if body.catalog_version_id is not None and (
                        catalog.next_cursor is not None
                        or any(item.version_id != body.catalog_version_id for item in catalog.items)
                        or len(catalog.items) > 1
                    ):
                        raise ValueError("Unbound catalog lookup")
                    if body.catalog_after is not None and any(
                        str(item.version_id) <= str(body.catalog_after) for item in catalog.items
                    ):
                        raise ValueError("Invalid catalog cursor")
                    if catalog.next_cursor is not None and (
                        not catalog.items or catalog.next_cursor != catalog.items[-1].version_id
                    ):
                        raise ValueError("Invalid next catalog cursor")
                elif purpose == "task-notice":
                    from reverse_hr.contracts.task_discovery import TaskNotice

                    notice = TaskNotice.model_validate(receipt.data)
                    if (
                        notice.notice_id != body.notice_id
                        or notice.recipient_id != body.candidate_id
                        or receipt.revision != 1
                    ):
                        raise ValueError("Unbound task notice")
                elif purpose == "appeal-notice":
                    notice = AppealNoticeView.model_validate(receipt.data)
                    if (
                        notice.notice_id != body.notice_id
                        or notice.recipient_id != body.candidate_id
                        or receipt.revision != 1
                    ):
                        raise ValueError("Unbound appeal notice")
                elif purpose == "company-notice":
                    notice = CompanyNoticeView.model_validate(receipt.data)
                    if (
                        notice.notice_id != body.notice_id
                        or notice.recipient_id != body.candidate_id
                        or receipt.revision != 1
                    ):
                        raise ValueError("Unbound company notice")
                elif purpose == "notice":
                    notice = NoticeView.model_validate(receipt.data)
                    if (
                        notice.notice_id != body.notice_id
                        or notice.recipient_id != body.candidate_id
                        or receipt.revision != 1
                    ):
                        raise ValueError("Unbound notice")
                elif purpose == "profile":
                    card = CandidateCard.model_validate(receipt.data)
                    if (
                        card.candidate_id != body.candidate_id
                        or card.version != receipt.revision
                        or (
                            body.specialization is not None
                            and card.specialization != body.specialization
                        )
                    ):
                        raise ValueError("Unbound candidate card")
                elif purpose == "need":
                    need = NeedView.model_validate(receipt.data)
                    if (
                        need.need_id != body.need_id
                        or need.organization_id != body.organization_id
                        or need.version != receipt.revision
                    ):
                        raise ValueError("Unbound need")
                elif purpose == "contacts":
                    contacts = ContactView.model_validate(receipt.data)
                    if (
                        contacts.candidate_id != body.candidate_id
                        or contacts.organization_id != body.organization_id
                    ):
                        raise ValueError("Unbound contact")
                elif purpose in {"membership", "affiliation", "content-membership"}:
                    if (
                        set(receipt.data) != {"organization_id", "role"}
                        or UUID(receipt.data["organization_id"]) != body.organization_id
                        or receipt.data["role"]
                        not in (
                            {"owner", "recruiter", "technical_expert"}
                            if purpose != "membership"
                            else {"owner", "recruiter"}
                        )
                    ):
                        raise ValueError("Unbound membership")
                elif purpose == "purpose-permission":
                    if (
                        set(receipt.data) != {"consent_id"}
                        or UUID(receipt.data["consent_id"]) != body.consent_id
                    ):
                        raise ValueError("Unbound consent")
                elif purpose == "company-result-permission":
                    if receipt.data != {"result_grant_id": str(body.result_grant_id)}:
                        raise ValueError("Invalid company result permission")
                elif purpose == "resume-permission":
                    if (
                        receipt.data != {"invitation_id": str(body.invitation_id)}
                        or receipt.revision < 1
                    ):
                        raise ValueError("Invalid resume permission")
                elif purpose == "contact-permission":
                    if set(receipt.data) != {"grant_id"}:
                        raise ValueError("Invalid grant")
                    UUID(receipt.data["grant_id"])

        except Exception as exc:
            raise HTTPException(503) from exc
        return receipt

    def require(self, owner, purpose, **refs):
        receipt = self.fetch(owner, purpose, **refs)
        if not receipt.allowed:
            raise HTTPException(409)
        return receipt


def respond(
    request: Request, body: MarketRequest, signature, owner, purpose, nonce_model, callers, checker
):
    from reverse_hr.shared.event_transport import Signatures

    if (
        signature is None
        or not fresh(body.issued_at)
        or body.purpose != purpose
        or body.requester not in callers
    ):
        raise HTTPException(401)
    try:
        signatures = getattr(
            request.app.state, owner + "_signatures", None
        ) or Signatures.from_settings(request.app.state.settings)
    except Exception as exc:
        raise HTTPException(503) from exc
    try:
        verify(signatures, body.requester, signature, context(owner, purpose, "request"), body)
    except Exception as exc:
        raise HTTPException(401) from exc
    now = datetime.now(UTC)
    try:
        with Session(request.app.state.engine) as session, session.begin():
            session.execute(delete(nonce_model).where(nonce_model.expires_at < now))
            values = dict(nonce=str(body.nonce), expires_at=now + timedelta(seconds=60))
            if hasattr(nonce_model, "requester"):
                values["requester"] = body.requester
            session.add(nonce_model(**values))
            session.flush()
            data, revision = checker(session)
            receipt = MarketReceipt(
                **(body.model_dump() | {"issued_at": datetime.now(UTC)}),
                allowed=data is not None,
                revision=revision,
                data=data,
            )
            raw = canonical(receipt)
            if len(raw) > MAX_BYTES:
                raise HTTPException(503)
            signed = sign(signatures, context(owner, purpose, "response"), receipt)
        return Response(
            content=raw,
            media_type="application/json",
            headers={"X-HR-Signature": signed, "Cache-Control": "no-store"},
        )
    except IntegrityError as exc:
        raise HTTPException(401) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
