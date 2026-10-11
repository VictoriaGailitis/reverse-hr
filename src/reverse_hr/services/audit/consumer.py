"""Audit transport preserves the exact signed producer proof before archiving."""

from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.services.audit.domain.audit import SUBJECT_KEYS, append, erase_subject
from reverse_hr.shared.event_transport import InvalidEvent, SignedConsumer


class AuditConsumer(SignedConsumer):
    service = "audit"

    def __init__(self, engine, signatures, settings, *, processing=None):
        super().__init__(engine, signatures, settings)
        self.processing = processing or ProcessingAccess(settings)
        if processing is None:
            self.processing._signatures = signatures

    def __call__(self, channel, method, properties, body):
        headers = dict(properties.headers or {})
        try:
            event = self.signatures.verify(body, headers, properties.message_id)
            if method.exchange not in {f"events.{event.producer}", "incoming.audit"}:
                raise InvalidEvent()
        except InvalidEvent:
            self.move(channel, method, b'{"code":"invalid_event"}', {}, None, "dead")
            return
        try:
            blocked = False
            for subject in {value for key, value in event.payload.items() if key in SUBJECT_KEYS}:
                try:
                    self.processing.check(subject)
                except HTTPException as exc:
                    if exc.status_code in {403, 404, 409}:
                        blocked = True
                    else:
                        raise
            with Session(self.engine) as session, session.begin():
                if event.event_type == "privacy.deletion_requested.v1":
                    erase_subject(session, event, self.settings, signatures=self.signatures)
                    blocked = True
                append(
                    session,
                    event,
                    body,
                    headers["hr-signature"],
                    self.signatures,
                    self.settings,
                    blocked=blocked,
                    now=datetime.now(UTC),
                )
        except HTTPException as exc:
            if exc.status_code >= 500:
                self.retry(channel, method, body, headers, event)
            else:
                self.move(
                    channel,
                    method,
                    body,
                    headers | {"hr-error": "business_rule"},
                    str(event.event_id),
                    "dead",
                )
            return
        except (OperationalError, IntegrityError):
            self.retry(channel, method, body, headers, event)
            return
        except Exception:
            self.retry(channel, method, body, headers, event)
            return
        channel.basic_ack(delivery_tag=method.delivery_tag)
