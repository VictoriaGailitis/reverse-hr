"""Verified email targets and durable consent-gated minimal external delivery."""

import base64
import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal
from uuid import UUID, uuid4, uuid5

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import DateTime, String, Text, UniqueConstraint, and_, delete, exists, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.protocols.audit_access import record_disclosure
from reverse_hr.protocols.market_access import Signature
from reverse_hr.protocols.market_state import lock
from reverse_hr.services.notification.domain.notification import (
    NotificationBase,
    NotificationRow,
    NotificationSubject,
    available,
)
from reverse_hr.services.notification.notification_provider import (
    ChallengeCipher,
    Mail,
    ProviderRejected,
    ProviderUncertain,
    static_https,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute
from reverse_hr.shared.db import IdempotencyRecord, Outbox
from reverse_hr.shared.signing import canonical, fresh

SERVICE_PURPOSE = "external_service_notifications"
MARKETING_PURPOSE = "external_marketing_notifications"
CALLBACK_CONTEXT = b"reverse-hr.notification-provider-callback.v1\0"
NAMESPACE = UUID("9eaa445b-4541-474d-a32c-5f485c23684e")


class EmailTarget(NotificationBase):
    __tablename__ = "notification_email_targets"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    email: Mapped[str] = mapped_column(String(320))
    verified: Mapped[bool]
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int]
    challenge_id: Mapped[str | None] = mapped_column(String(36))
    next_challenge_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rate_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    rate_count: Mapped[int]


class EmailRateWindow(NotificationBase):
    __tablename__ = "notification_email_rate_windows"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used: Mapped[int]


class EmailPreference(NotificationBase):
    __tablename__ = "notification_email_preferences"
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    service_email: Mapped[bool]
    marketing_email: Mapped[bool]
    service_consent_id: Mapped[str | None] = mapped_column(String(36))
    marketing_consent_id: Mapped[str | None] = mapped_column(String(36))
    version: Mapped[int]
    service_activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    marketing_activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EmailChallenge(NotificationBase):
    __tablename__ = "notification_email_challenges"
    challenge_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject: Mapped[str] = mapped_column(String(36), index=True)
    target_version: Mapped[int]
    salt: Mapped[str] = mapped_column(String(64))
    code_digest: Mapped[str] = mapped_column(String(64))
    ciphertext: Mapped[str | None] = mapped_column(Text)
    consent_id: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int]
    status: Mapped[str] = mapped_column(String(16))


class Delivery(NotificationBase):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint("notice_id", "target_version"),
        UniqueConstraint("challenge_id"),
    )
    delivery_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject: Mapped[str] = mapped_column(String(36), index=True)
    notice_id: Mapped[str | None] = mapped_column(String(36), index=True)
    challenge_id: Mapped[str | None] = mapped_column(String(36))
    target_version: Mapped[int]
    category: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int]
    next_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    provider_id: Mapped[str | None] = mapped_column(String(36))
    callback_sequence: Mapped[int]
    version: Mapped[int]


class Attempt(NotificationBase):
    __tablename__ = "notification_delivery_attempts"
    delivery_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    number: Mapped[int] = mapped_column(primary_key=True)
    lease_token: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CallbackReceipt(NotificationBase):
    __tablename__ = "notification_delivery_callbacks"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    nonce: Mapped[str] = mapped_column(String(36), unique=True)
    delivery_id: Mapped[str] = mapped_column(String(36), index=True)
    digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class TargetCommand(Contract):
    email: str = Field(
        min_length=3,
        max_length=254,
        pattern=r"^[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}$",
    )
    consent_id: UUID


class VerifyCommand(Contract):
    challenge_id: UUID
    code: str = Field(pattern=r"^[0-9]{6}$")


class EmailPreferences(Contract):
    service_email: bool = Field(strict=True)
    marketing_email: bool = Field(strict=True)
    service_consent_id: UUID | None = None
    marketing_consent_id: UUID | None = None


class ProviderCallback(Contract):
    delivery_id: UUID
    provider_id: UUID
    event_id: UUID
    nonce: UUID
    sequence: int = Field(ge=1, strict=True)
    status: Literal["delivered", "failed"]
    issued_at: datetime


router = APIRouter(prefix="/v1/notifications", tags=["external-notification"])
internal_router = APIRouter(prefix="/internal/v1/notifications", tags=["provider-callback"])


def utc(value):
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def enabled(request):
    if not request.app.state.settings.notification_delivery_enabled:
        raise HTTPException(409, "External delivery disabled")


def cipher(request):
    explicit = getattr(request.app.state, "notification_challenge_cipher", None)
    return explicit if explicit else ChallengeCipher.from_settings(request.app.state.settings)


def purpose(request, subject, consent, category):
    if not consent:
        raise HTTPException(409)
    request.app.state.market_access.require(
        "privacy",
        "purpose-permission",
        candidate_id=UUID(str(subject)),
        consent_id=UUID(str(consent)),
        consent_purpose=MARKETING_PURPOSE if category == "marketing" else SERVICE_PURPOSE,
    )


def cancel(session, subject, *, category=None):
    query = select(Delivery).where(
        Delivery.subject == str(subject),
        Delivery.status.not_in(["delivered", "failed", "cancelled"]),
    )
    if category:
        query = query.where(Delivery.category == category)
    for row in session.scalars(query):
        row.status, row.lease_token, row.lease_until, row.version = (
            "cancelled",
            None,
            None,
            row.version + 1,
        )


def delivery_view(row):
    return {
        "delivery_id": row.delivery_id,
        "notice_id": row.notice_id,
        "category": row.category,
        "status": row.status,
        "attempts": row.attempts,
        "version": row.version,
    }


@router.post("/email", status_code=201)
def begin(request: Request, actor: Actor, body: TargetCommand, idempotency: CommandKey):
    enabled(request)
    purpose(request, actor.subject, body.consent_id, "verification")
    code = f"{secrets.randbelow(1000000):06d}"
    challenge_id = str(uuid4())
    encrypted = cipher(request).encrypt(code, challenge_id)
    now = datetime.now(UTC)

    def guard(session):
        lock(session, NotificationSubject, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        purpose(request, actor.subject, body.consent_id, "verification")

    def change(session):
        rate = session.get(EmailRateWindow, str(actor.subject))
        if rate and utc(rate.started_at) + timedelta(hours=1) <= now:
            rate.started_at, rate.used = now, 0
        if rate and (utc(rate.next_at) > now or rate.used >= 3):
            raise HTTPException(429)
        if rate is None:
            rate = EmailRateWindow(subject=str(actor.subject), started_at=now, next_at=now, used=0)
            session.add(rate)
        rate.used, rate.next_at = rate.used + 1, now + timedelta(minutes=1)
        row = session.get(EmailTarget, str(actor.subject))
        if row and (
            utc(row.next_challenge_at) > now
            or (utc(row.rate_started_at) + timedelta(hours=1) > now and row.rate_count >= 3)
        ):
            raise HTTPException(429)
        version = row.version + 1 if row else 1
        if row:
            row.verified_at = None
            row.email, row.verified, row.version, row.challenge_id = (
                body.email.casefold(),
                False,
                version,
                challenge_id,
            )
            if utc(row.rate_started_at) + timedelta(hours=1) <= now:
                row.rate_started_at, row.rate_count = now, 0
            row.rate_count += 1
            row.next_challenge_at = now + timedelta(minutes=1)
        else:
            row = EmailTarget(
                subject=str(actor.subject),
                email=body.email.casefold(),
                verified=False,
                version=version,
                challenge_id=challenge_id,
                next_challenge_at=now + timedelta(minutes=1),
                rate_started_at=now,
                rate_count=1,
            )
            session.add(row)
        cancel(session, actor.subject)
        for old in session.scalars(
            select(EmailChallenge).where(EmailChallenge.subject == str(actor.subject))
        ):
            old.ciphertext, old.status = None, "cancelled"
        salt = secrets.token_hex(32)
        session.add(
            EmailChallenge(
                challenge_id=challenge_id,
                subject=str(actor.subject),
                target_version=version,
                salt=salt,
                code_digest=hashlib.sha256((salt + code).encode()).hexdigest(),
                ciphertext=encrypted,
                consent_id=str(body.consent_id),
                expires_at=now + timedelta(minutes=10),
                attempts=0,
                status="pending",
            )
        )
        session.add(
            Delivery(
                delivery_id=str(uuid5(NAMESPACE, challenge_id)),
                subject=str(actor.subject),
                notice_id=None,
                challenge_id=challenge_id,
                target_version=version,
                category="verification",
                status="pending",
                attempts=0,
                next_at=now,
                lease_token=None,
                lease_until=None,
                provider_id=None,
                callback_sequence=0,
                version=1,
            )
        )
        return {
            "challenge_id": challenge_id,
            "expires_at": (now + timedelta(minutes=10)).isoformat(),
            "target_version": version,
        }

    return execute(
        request.app.state.engine,
        actor.subject,
        "notification_email_challenge",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
    )


@router.post("/email/verify")
def confirm(request: Request, actor: Actor, body: VerifyCommand):
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, NotificationSubject, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        target = session.get(EmailTarget, str(actor.subject))
        challenge = session.get(EmailChallenge, str(body.challenge_id))
        if challenge is None or challenge.subject != str(actor.subject):
            raise HTTPException(404)
        if (
            target is None
            or target.challenge_id != challenge.challenge_id
            or target.version != challenge.target_version
            or challenge.status not in {"pending", "sent"}
            or utc(challenge.expires_at) <= datetime.now(UTC)
            or challenge.attempts >= 5
        ):
            raise HTTPException(409)
        challenge.attempts += 1
        matches = secrets.compare_digest(
            challenge.code_digest, hashlib.sha256((challenge.salt + body.code).encode()).hexdigest()
        )
        if matches:
            purpose(request, actor.subject, challenge.consent_id, "verification")
            target.verified, challenge.status, challenge.ciphertext = True, "verified", None
            target.verified_at = datetime.now(UTC)
            result = {"verified": True, "target_version": target.version}
        else:
            if challenge.attempts >= 5:
                challenge.status, challenge.ciphertext = "locked", None
            result = {"verified": False, "attempts_remaining": 5 - challenge.attempts}
    return result


@router.get("/email")
def get_target(request: Request, actor: Actor):
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, NotificationSubject, actor.subject)
        row = session.get(EmailTarget, str(actor.subject))
        return (
            {"email": row.email, "verified": row.verified, "version": row.version}
            if row
            else {"email": None, "verified": False, "version": 0}
        )


@router.put("/email/preferences")
def preferences(
    request: Request,
    actor: Actor,
    body: EmailPreferences,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):

    def guard(session):
        lock(session, NotificationSubject, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        for category, flag, consent in [
            ("service", body.service_email, body.service_consent_id),
            ("marketing", body.marketing_email, body.marketing_consent_id),
        ]:
            if flag:
                purpose(request, actor.subject, consent, category)

    def change(session):
        row = session.get(EmailPreference, str(actor.subject))
        if (row.version if row else 1) != int(if_match.strip('"')):
            raise HTTPException(409)
        target = session.get(EmailTarget, str(actor.subject))
        if (body.service_email or body.marketing_email) and (target is None or not target.verified):
            raise HTTPException(409)
        values = body.model_dump(mode="json")
        if row:
            if body.service_email and not row.service_email:
                row.service_activated_at = datetime.now(UTC)
            if body.marketing_email and not row.marketing_email:
                row.marketing_activated_at = datetime.now(UTC)
            for key, value in values.items():
                setattr(row, key, value)
            row.version += 1
        else:
            row = EmailPreference(
                subject=str(actor.subject),
                version=2,
                service_activated_at=datetime.now(UTC) if body.service_email else None,
                marketing_activated_at=datetime.now(UTC) if body.marketing_email else None,
                **values,
            )
            session.add(row)
        if not body.service_email:
            cancel(session, actor.subject, category="service")
        if not body.marketing_email:
            cancel(session, actor.subject, category="marketing")
        if not body.service_email and not body.marketing_email:
            cancel(session, actor.subject)
            session.execute(
                delete(EmailChallenge).where(EmailChallenge.subject == str(actor.subject))
            )
            if target:
                session.delete(target)
        return values | {"version": row.version}

    return execute(
        request.app.state.engine,
        actor.subject,
        "notification_email_preferences",
        idempotency,
        body.model_dump(mode="json") | {"version": if_match},
        change,
        guard=guard,
    )


@router.get("/email/preferences")
def get_email_preferences(request: Request, actor: Actor):
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, NotificationSubject, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        row = session.get(EmailPreference, str(actor.subject))
        return {
            "service_email": row.service_email if row else False,
            "marketing_email": row.marketing_email if row else False,
            "version": row.version if row else 1,
        }


@router.get("/deliveries")
def listing(request: Request, actor: Actor, after: UUID | None = None):
    with Session(request.app.state.engine) as session, session.begin():
        lock(session, NotificationSubject, actor.subject)
        query = select(Delivery).where(Delivery.subject == str(actor.subject))
        if after:
            query = query.where(Delivery.delivery_id > str(after))
        return [
            delivery_view(row)
            for row in session.scalars(query.order_by(Delivery.delivery_id).limit(50))
        ]


def fanout_one(request, *, now=None):
    now = now or datetime.now(UTC)
    with Session(request.app.state.engine) as session, session.begin():
        pending = (
            select(NotificationRow)
            .join(EmailTarget, EmailTarget.subject == NotificationRow.recipient_id)
            .join(EmailPreference, EmailPreference.subject == NotificationRow.recipient_id)
            .join(NotificationSubject, NotificationSubject.subject == NotificationRow.recipient_id)
            .where(
                EmailTarget.verified.is_(True),
                NotificationSubject.blocked.is_(False),
                NotificationRow.created_at >= EmailTarget.verified_at,
                or_(
                    and_(
                        NotificationRow.category == "marketing",
                        EmailPreference.marketing_email.is_(True),
                        NotificationRow.created_at >= EmailPreference.marketing_activated_at,
                    ),
                    and_(
                        NotificationRow.category != "marketing",
                        EmailPreference.service_email.is_(True),
                        NotificationRow.created_at >= EmailPreference.service_activated_at,
                    ),
                ),
                ~exists().where(
                    Delivery.notice_id == NotificationRow.notice_id,
                    Delivery.target_version == EmailTarget.version,
                ),
            )
            .order_by(NotificationRow.notice_id)
            .limit(50)
        )
        for notice in session.scalars(pending):
            target = session.get(EmailTarget, notice.recipient_id)
            prefs = session.get(EmailPreference, notice.recipient_id)
            if not target or not target.verified or not prefs:
                continue
            flag = prefs.marketing_email if notice.category == "marketing" else prefs.service_email
            if not flag:
                continue
            key = str(uuid5(NAMESPACE, notice.notice_id + ":" + str(target.version)))
            if session.get(Delivery, key):
                continue
            try:
                lock(session, NotificationSubject, notice.recipient_id)
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                raise
            session.refresh(target)
            session.refresh(prefs)
            if not target.verified or not (
                prefs.marketing_email if notice.category == "marketing" else prefs.service_email
            ):
                continue
            activated = (
                prefs.marketing_activated_at
                if notice.category == "marketing"
                else prefs.service_activated_at
            )
            if (
                not activated
                or not target.verified_at
                or utc(notice.created_at) < max(utc(activated), utc(target.verified_at))
            ):
                continue
            key = str(uuid5(NAMESPACE, notice.notice_id + ":" + str(target.version)))
            if session.get(Delivery, key):
                continue
            session.add(
                Delivery(
                    delivery_id=key,
                    subject=notice.recipient_id,
                    notice_id=notice.notice_id,
                    challenge_id=None,
                    target_version=target.version,
                    category=notice.category,
                    status="pending",
                    attempts=0,
                    next_at=now,
                    lease_token=None,
                    lease_until=None,
                    provider_id=None,
                    callback_sequence=0,
                    version=1,
                )
            )
            return True
    return False


def claim(request, *, now=None):
    now = now or datetime.now(UTC)
    settings = request.app.state.settings
    with Session(request.app.state.engine) as session, session.begin():
        job = session.scalar(
            select(Delivery)
            .where(
                Delivery.status.in_(["pending", "uncertain", "attempting"]),
                Delivery.next_at <= now,
                Delivery.attempts < settings.notification_delivery_max_attempts,
            )
            .order_by(Delivery.next_at, Delivery.delivery_id)
            .limit(1)
        )
        if job is None:
            return None
        if job.status == "attempting" and job.lease_until and utc(job.lease_until) > now:
            return None
        lock(session, NotificationSubject, job.subject)
        session.refresh(job, with_for_update=True)
        if (
            job.status not in {"pending", "uncertain", "attempting"}
            or utc(job.next_at) > now
            or job.attempts >= settings.notification_delivery_max_attempts
            or (job.lease_until and utc(job.lease_until) > now)
        ):
            return None
        job.attempts += 1
        job.status, job.lease_token, job.lease_until, job.version = (
            "attempting",
            str(uuid4()),
            now + timedelta(seconds=settings.notification_delivery_lease_seconds),
            job.version + 1,
        )
        job.next_at = job.lease_until
        session.add(
            Attempt(
                delivery_id=job.delivery_id,
                number=job.attempts,
                lease_token=job.lease_token,
                status="claimed",
                at=now,
            )
        )
        return job.delivery_id, job.lease_token


def authorize_job(request, session, job, *, now):
    target = session.get(EmailTarget, job.subject)
    if not target or target.version != job.target_version:
        raise HTTPException(409)
    request.app.state.processing_access.check(UUID(job.subject))
    if job.category == "verification":
        challenge = session.get(EmailChallenge, job.challenge_id)
        if (
            not challenge
            or challenge.status not in {"pending", "sent"}
            or not challenge.ciphertext
            or utc(challenge.expires_at) <= now
            or target.challenge_id != challenge.challenge_id
        ):
            raise HTTPException(409)
        purpose(request, job.subject, challenge.consent_id, "verification")
        code = cipher(request).decrypt(challenge.ciphertext, challenge.challenge_id)
        text = "Код подтверждения адреса: " + code + ". Действует 10 минут."
    else:
        prefs = session.get(EmailPreference, job.subject)
        if (
            not target.verified
            or not prefs
            or not (prefs.marketing_email if job.category == "marketing" else prefs.service_email)
        ):
            raise HTTPException(409)
        consent = (
            prefs.marketing_consent_id if job.category == "marketing" else prefs.service_consent_id
        )
        purpose(request, job.subject, consent, job.category)
        notice = session.get(NotificationRow, job.notice_id)
        if (
            not notice
            or notice.recipient_id != job.subject
            or notice.category != job.category
            or not available(request, notice, channel="email")
        ):
            raise HTTPException(409)
        text = "В платформе доступно новое уведомление. Откройте личный кабинет: " + static_https(
            request.app.state.settings.notification_application_link
        )
    return Mail(job.delivery_id, target.email, text)


def audit_authorization(request, delivery_id, lease_token, now):
    with Session(request.app.state.engine) as session, session.begin():
        job = session.get(Delivery, delivery_id)
        if job is None:
            return False
        lock(session, NotificationSubject, job.subject)
        session.refresh(job, with_for_update=True)
        if (
            job.status != "attempting"
            or job.lease_token != lease_token
            or not job.lease_until
            or utc(job.lease_until) <= now
        ):
            return False
        attempt = session.get(Attempt, (job.delivery_id, job.attempts))
        try:
            authorize_job(request, session, job, now=now)
        except HTTPException:
            return True
        if attempt.status == "claimed":
            record_disclosure(
                session,
                request,
                "external_delivery",
                UUID(job.delivery_id),
                UUID(job.subject),
                UUID(job.subject),
                effect_id=uuid5(NAMESPACE, job.delivery_id + ":attempt:" + str(job.attempts)),
            )
            attempt.status = "authorized"
    return True


def send_claim(request, provider, delivery_id, lease_token, *, now=None):
    explicit_clock = now is not None
    now = now or datetime.now(UTC)
    if not audit_authorization(request, delivery_id, lease_token, now):
        return False
    # Keep the local subject fence through the provider call. Preference changes,
    # address replacement and Privacy cannot commit while a send is in flight.
    # Remote consent is checked immediately before send, not just before claim.
    with Session(request.app.state.engine) as session, session.begin():
        job = session.get(Delivery, delivery_id)
        if not job:
            return False
        lock(session, NotificationSubject, job.subject)
        session.refresh(job, with_for_update=True)
        if (
            job.status != "attempting"
            or job.lease_token != lease_token
            or not job.lease_until
            or utc(job.lease_until) <= now
        ):
            return False
        attempt = session.get(Attempt, (job.delivery_id, job.attempts))
        try:
            mail = authorize_job(request, session, job, now=now)
        except HTTPException as exc:
            if exc.status_code >= 500:
                job.status, attempt.status = "uncertain", "permission_retry"
                job.next_at = now + timedelta(
                    seconds=request.app.state.settings.notification_delivery_retry_seconds
                )
            else:
                job.status, attempt.status = "cancelled", "cancelled"
                if job.challenge_id:
                    challenge = session.get(EmailChallenge, job.challenge_id)
                    if challenge:
                        challenge.ciphertext, challenge.status = None, "cancelled"
            job.lease_token, job.lease_until, job.version = None, None, job.version + 1
            return True
        # A failed first permission check may recover during the final check.
        # Retry with a new committed Audit receipt rather than sending unjournaled data.
        if attempt.status != "authorized":
            job.status, attempt.status = "uncertain", "audit_retry"
            job.next_at = now + timedelta(
                seconds=request.app.state.settings.notification_delivery_retry_seconds
            )
            job.lease_token, job.lease_until, job.version = None, None, job.version + 1
            return True
        # Refresh wall time after permission RPCs; a lease or challenge can expire during them.
        if not explicit_clock:
            now = datetime.now(UTC)
            if utc(job.lease_until) <= now:
                return False
            if job.challenge_id:
                challenge = session.get(EmailChallenge, job.challenge_id)
                if utc(challenge.expires_at) <= now:
                    job.status, attempt.status = "cancelled", "cancelled"
                    challenge.ciphertext, challenge.status = None, "expired"
                    job.lease_token, job.lease_until = None, None
                    job.version += 1
                    return True
        # The durable authorization receipt precedes this final fresh permission check.
        try:
            provider_id = str(UUID(provider.send(mail)))
        except ProviderRejected:
            job.status, attempt.status = "failed", "rejected"
        except (ProviderUncertain, TimeoutError, ValueError):
            job.status, attempt.status = "uncertain", "uncertain"
            job.next_at = now + timedelta(
                seconds=min(
                    3600,
                    request.app.state.settings.notification_delivery_retry_seconds
                    * 2 ** (job.attempts - 1),
                )
            )
        else:
            job.status, job.provider_id, attempt.status = (
                "submitted",
                str(UUID(provider_id)),
                "submitted",
            )
            if job.challenge_id:
                challenge = session.get(EmailChallenge, job.challenge_id)
                challenge.status = "sent"
        job.lease_token, job.lease_until, job.version = None, None, job.version + 1
    return True


def run_one(request, provider, *, now=None):
    if not request.app.state.settings.notification_delivery_enabled:
        return False
    with Session(request.app.state.engine) as session, session.begin():
        exhausted = session.scalar(
            select(Delivery)
            .where(
                Delivery.status.in_(["pending", "uncertain", "attempting"]),
                Delivery.attempts >= request.app.state.settings.notification_delivery_max_attempts,
                Delivery.next_at <= (now or datetime.now(UTC)),
            )
            .order_by(Delivery.delivery_id)
            .limit(1)
        )
        if exhausted:
            lock(session, NotificationSubject, exhausted.subject)
            session.refresh(exhausted, with_for_update=True)
            if not exhausted.lease_until or utc(exhausted.lease_until) <= (
                now or datetime.now(UTC)
            ):
                (
                    exhausted.status,
                    exhausted.lease_token,
                    exhausted.lease_until,
                    exhausted.version,
                ) = "uncertain_final", None, None, exhausted.version + 1
                return True
        session.execute(
            delete(EmailRateWindow).where(
                EmailRateWindow.started_at <= (now or datetime.now(UTC)) - timedelta(hours=1)
            )
        )
        expired = session.scalar(
            select(EmailChallenge)
            .where(
                EmailChallenge.expires_at <= (now or datetime.now(UTC)),
                EmailChallenge.ciphertext.is_not(None),
            )
            .order_by(EmailChallenge.expires_at)
            .limit(1)
        )
        if expired:
            lock(session, NotificationSubject, expired.subject, allow_blocked=True)
            expired.ciphertext, expired.status = None, "expired"
            cancel(session, expired.subject, category="verification")
            return True
        session.execute(
            delete(CallbackReceipt).where(CallbackReceipt.expires_at <= (now or datetime.now(UTC)))
        )
    claimed = claim(request, now=now)
    if claimed:
        return send_claim(request, provider, *claimed, now=now)
    return fanout_one(request, now=now)


@router.post("/provider-callback")
@internal_router.post("/provider-callback")
def callback(request: Request, body: ProviderCallback, signature: Signature):
    enabled(request)
    if not fresh(body.issued_at):
        raise HTTPException(409)
    explicit = getattr(request.app.state, "notification_provider_callback_key", None)
    key = (
        explicit
        if explicit
        else Ed25519PublicKey.from_public_bytes(
            Path(
                request.app.state.settings.notification_provider_callback_public_key_file
            ).read_bytes()
        )
    )
    try:
        key.verify(base64.b64decode(signature, validate=True), CALLBACK_CONTEXT + canonical(body))
    except Exception as exc:
        raise HTTPException(401) from exc
    content = hashlib.sha256(canonical(body)).hexdigest()
    with Session(request.app.state.engine) as session, session.begin():
        prior = session.get(CallbackReceipt, str(body.event_id))
        if prior:
            if prior.digest != content:
                raise HTTPException(409)
            return {"accepted": True, "replayed": True}
        if session.scalar(select(CallbackReceipt).where(CallbackReceipt.nonce == str(body.nonce))):
            raise HTTPException(409)
        job = session.get(Delivery, str(body.delivery_id))
        if not job:
            raise HTTPException(404)
        lock(session, NotificationSubject, job.subject, allow_blocked=True)
        session.refresh(job, with_for_update=True)
        # Recheck under the subject fence. A savepoint translates cross-subject
        # unique-event/nonce races into an idempotent receipt or explicit conflict.
        prior = session.get(CallbackReceipt, str(body.event_id))
        if prior:
            if prior.digest != content:
                raise HTTPException(409)
            return {"accepted": True, "replayed": True}
        try:
            with session.begin_nested():
                session.add(
                    CallbackReceipt(
                        event_id=str(body.event_id),
                        nonce=str(body.nonce),
                        delivery_id=job.delivery_id,
                        digest=content,
                        expires_at=datetime.now(UTC) + timedelta(days=1),
                    )
                )
                session.flush()
        except IntegrityError:
            prior = session.get(CallbackReceipt, str(body.event_id))
            if prior and prior.digest == content:
                return {"accepted": True, "replayed": True}
            raise HTTPException(409) from None
        if job.status == "cancelled" or body.sequence <= job.callback_sequence:
            return {"accepted": True, "ignored": True}
        if job.status not in {
            "attempting",
            "submitted",
            "uncertain",
            "uncertain_final",
            "delivered",
            "failed",
        } or (job.provider_id and job.provider_id != str(body.provider_id)):
            raise HTTPException(409)
        # Provider corrections may advance sequence, but cannot turn a terminal
        # delivered message into failed or revive a permanent local rejection.
        if job.status in {"delivered", "failed"}:
            return {"accepted": True, "ignored": True}
        job.provider_id, job.callback_sequence, job.status, job.version = (
            str(body.provider_id),
            body.sequence,
            body.status,
            job.version + 1,
        )
        job.lease_token, job.lease_until = None, None
        return {"accepted": True}


def purge(session, subject):
    notices = select(NotificationRow.notice_id).where(
        (NotificationRow.recipient_id == str(subject))
        | (NotificationRow.candidate_id == str(subject))
        | (NotificationRow.creator_id == str(subject))
        | (NotificationRow.author_id == str(subject))
    )
    ids = select(Delivery.delivery_id).where(
        (Delivery.subject == str(subject)) | Delivery.notice_id.in_(notices)
    )
    session.execute(delete(Attempt).where(Attempt.delivery_id.in_(ids)))
    session.execute(delete(CallbackReceipt).where(CallbackReceipt.delivery_id.in_(ids)))
    session.execute(delete(Delivery).where(Delivery.delivery_id.in_(ids)))
    for model in (EmailChallenge, EmailTarget, EmailPreference, EmailRateWindow):
        session.execute(delete(model).where(model.subject == str(subject)))
    session.execute(delete(IdempotencyRecord).where(IdempotencyRecord.actor_id == str(subject)))
    session.execute(
        delete(Outbox).where(Outbox.envelope["payload"]["candidate_id"].as_string() == str(subject))
    )


def subject_export_records(session, subject):
    target = session.get(EmailTarget, str(subject))
    if target:
        yield {
            "table": "notification_email_targets",
            "key": str(subject),
            "data": {"email": target.email, "verified": target.verified, "version": target.version},
        }
    prefs = session.get(EmailPreference, str(subject))
    if prefs:
        yield {
            "table": "notification_email_preferences",
            "key": str(subject),
            "data": {
                "service_email": prefs.service_email,
                "marketing_email": prefs.marketing_email,
                "version": prefs.version,
            },
        }
    for row in session.scalars(
        select(Delivery)
        .where(Delivery.subject == str(subject))
        .order_by(Delivery.delivery_id)
        .execution_options(yield_per=64)
    ):
        yield {
            "table": "notification_deliveries",
            "key": row.delivery_id,
            "data": delivery_view(row),
        }
