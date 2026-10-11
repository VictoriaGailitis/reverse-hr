"""Explainable communication signals, linked to independently reviewed complaints.

Heuristic signals are suspicions, never findings or automatic sanctions. Evidence
remains in the original access-controlled message store; no URL/text copies.
"""

import ipaddress
import re
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from fastapi import HTTPException, Request
from sqlalchemy import JSON, String, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.services.hiring.domain.hiring import HiringBase, InvitationRow, emit, router
from reverse_hr.services.hiring.domain.hiring_dialogs import Complaint, Message, dialog_guard
from reverse_hr.services.hiring.domain.hiring_moderation import ComplaintCase, guard_case
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.db import IdempotencyRecord, Outbox

RULE_VERSION = "communication-risk-rules-v2"


class CommunicationRisk(HiringBase):
    __tablename__ = "hiring_communication_risks"
    message_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    dialog_id: Mapped[str] = mapped_column(String(36), index=True)
    complaint_id: Mapped[str] = mapped_column(String(36), unique=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    data: Mapped[dict] = mapped_column(JSON)


def signals(text, terms, *, employer_message=True):
    """Bounded deterministic screening; ordinary HTTPS links aren't suspicious."""
    from reverse_hr.shared.prompt_injection import detect

    result = detect(text)
    for match in re.finditer(r"https?://[^\s<>]+", text, re.IGNORECASE):
        try:
            parsed = urlsplit(match.group().rstrip(".,);"))
            host = (parsed.hostname or "").lower()
            suspicious = (
                parsed.scheme.lower() != "https"
                or parsed.username is not None
                or host.startswith("xn--")
                or ".xn--" in host
                or host in {"bit.ly", "tinyurl.com", "t.co", "goo.gl"}
            )
            try:
                ipaddress.ip_address(host)
                suspicious = True
            except ValueError:
                pass
            if suspicious:
                result.append("suspicious_link")
                break
        except ValueError:
            result.append("suspicious_link")
            break
    # Require a request, rather than merely mentioning money. Negated requests
    # intentionally do not generate this signal.
    lower = text.casefold()
    request = re.search(
        r"(?<!не )\b(?:переведите|переведи|оплатите|оплати|заплатите|заплати|"
        r"send|transfer|pay)\b",
        lower,
    )
    financial = re.search(
        r"\b(?:деньги|депозит|взнос|залог|руб|рублей|money|deposit|fee|rub)\b", lower
    )
    if (
        request
        and financial
        and not re.search(r"\b(?:do not|don't|never)\s+(?:send|pay|transfer)\b", lower)
    ):
        result.append("payment_request")
    # Only explicit employer salary assertions in the offer's currency are
    # compared. Questions/negotiation are left to humans, not inferred as fraud.
    salary = terms.get("salary", {})
    if employer_message and salary.get("currency") and "?" not in text:
        for match in re.finditer(
            r"(?:зарплата|оклад|salary)\s*[:=]\s*(\d{1,9})\s*([A-Z]{3}|руб(?:лей)?)(?:\b|\.)",
            text,
            re.IGNORECASE,
        ):
            currency = match.group(2).upper()
            if currency in {"РУБ", "РУБЛЕЙ"}:
                currency = "RUB"
            if currency != salary["currency"]:
                continue
            amount = int(match.group(1))
            if amount < salary["minimum"] or amount > salary["maximum"]:
                result.append("salary_terms_mismatch")
                break
    return sorted(set(result))


def screen(session, request, invitation, message):
    codes = signals(
        message.text,
        invitation.spec,
        employer_message=message.author_id != invitation.candidate_id,
    )
    if not codes or session.get(CommunicationRisk, message.message_id):
        return
    complaint_id = str(uuid4())
    session.add(
        Complaint(
            complaint_id=complaint_id,
            dialog_id=message.dialog_id,
            author_id=message.author_id,
            message_id=message.message_id,
            reason="Automated suspicion; independent human review required: " + ", ".join(codes),
            created_at=datetime.now(UTC),
        )
    )
    session.add(ComplaintCase(complaint_id=complaint_id, status="open", version=1))
    session.add(
        CommunicationRisk(
            message_id=message.message_id,
            dialog_id=message.dialog_id,
            complaint_id=complaint_id,
            author_id=message.author_id,
            data={
                "rule_version": RULE_VERSION,
                "codes": codes,
                "offer_version": invitation.version,
            },
        )
    )
    emit(
        session,
        request,
        complaint_id,
        1,
        "communication_risk_detected",
        {
            "complaint_id": UUID(complaint_id),
            "message_id": UUID(message.message_id),
            "candidate_id": UUID(invitation.candidate_id),
            "organization_id": UUID(invitation.organization_id),
        },
    )


@router.get("/dialogs/{dialog_id}/risk-signals")
def listing(request: Request, actor: Actor, dialog_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        dialog_guard(request, actor, dialog_id, session, communication=False)
        rows = list(
            session.scalars(
                select(CommunicationRisk)
                .where(CommunicationRisk.dialog_id == str(dialog_id))
                .order_by(CommunicationRisk.message_id)
                .limit(50)
            )
        )
        result = []
        for row in rows:
            request.app.state.processing_access.check(UUID(row.author_id))
            case = session.get(ComplaintCase, row.complaint_id)
            if case:
                result.append(
                    {
                        "message_id": row.message_id,
                        "complaint_id": row.complaint_id,
                        "status": case.status,
                        **row.data,
                    }
                )
        return result


@router.get("/hiring-complaints/{complaint_id}/risk-signal")
def evidence(request: Request, actor: Actor, complaint_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        guard_case(request, actor, session, complaint_id)
        row = session.scalar(
            select(CommunicationRisk).where(CommunicationRisk.complaint_id == str(complaint_id))
        )
        if row is None:
            raise HTTPException(404)
        return {"message_id": row.message_id, **row.data}


def scrub(session, subject):
    from reverse_hr.services.hiring.domain.hiring_moderation import ComplaintDecision

    ids = select(InvitationRow.invitation_id).where(
        (InvitationRow.candidate_id == subject) | (InvitationRow.created_by == subject)
    )
    rows = list(
        session.scalars(
            select(CommunicationRisk).where(
                CommunicationRisk.dialog_id.in_(ids)
                | (CommunicationRisk.author_id == subject)
                | CommunicationRisk.complaint_id.in_(
                    select(ComplaintDecision.complaint_id).where(
                        ComplaintDecision.reviewer_id == subject
                    )
                )
                | CommunicationRisk.message_id.in_(
                    select(Message.message_id).where(Message.author_id == subject)
                )
            )
        )
    )
    references = [r.complaint_id for r in rows]
    if references:
        session.execute(
            delete(Outbox).where(Outbox.envelope["aggregate_id"].as_string().in_(references))
        )
        for ref in references:
            session.execute(
                delete(IdempotencyRecord).where(IdempotencyRecord.response.contains(ref))
            )
    session.execute(
        delete(CommunicationRisk).where(
            CommunicationRisk.message_id.in_([r.message_id for r in rows])
        )
    )
