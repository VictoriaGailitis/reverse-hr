"""Signed at-least-once transport. No business effect before signature validation."""

import base64
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pika
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.db import Outbox
from reverse_hr.domains.assessment_sessions import (
    process_deletion_request as process_assessment_deletion,
)
from reverse_hr.domains.candidate import process_deletion_request
from reverse_hr.domains.coding_workspace import (
    process_deletion_request as process_workspace_deletion,
)
from reverse_hr.domains.employer import process_deletion_request as process_employer_deletion
from reverse_hr.domains.privacy import process_accepted_invitation, process_deletion_ack
from reverse_hr.events import EventEnvelope
from reverse_hr.settings import SERVICES, Settings

MAX_EVENT_BYTES = 65536


class InvalidEvent(Exception):
    pass


def canonical(event: EventEnvelope) -> bytes:
    return json.dumps(event.model_dump(mode="json"), sort_keys=True, separators=(",", ":")).encode()


class Signatures:
    def __init__(self, service, private_key: bytes, public_keys: dict[str, str]):
        if service not in SERVICES:
            raise ValueError("Unknown signing identity")
        self.service = service
        self.private = Ed25519PrivateKey.from_private_bytes(private_key)
        self.public = {
            name: Ed25519PublicKey.from_public_bytes(base64.b64decode(key, validate=True))
            for name, key in public_keys.items()
        }

    @classmethod
    def from_settings(cls, settings):
        return cls(
            settings.service_name,
            Path(settings.event_private_key_file).read_bytes(),
            json.loads(Path(settings.event_public_keys_file).read_text()),
        )

    def sign(self, event):
        if event.producer != self.service or not event.event_type.startswith(self.service + "."):
            raise InvalidEvent()
        body = canonical(event)
        if len(body) > MAX_EVENT_BYTES:
            raise InvalidEvent()
        return body, {
            "hr-producer": self.service,
            "hr-signature": base64.b64encode(self.private.sign(body)).decode(),
        }

    def verify(self, body, headers, message_id):
        try:
            if len(body) > MAX_EVENT_BYTES:
                raise InvalidEvent()
            producer = headers["hr-producer"]
            self.public[producer].verify(
                base64.b64decode(headers["hr-signature"], validate=True), body
            )
            event = EventEnvelope.model_validate_json(body)
            if (
                event.producer != producer
                or str(event.event_id) != message_id
                or not event.event_type.startswith(producer + ".")
                or canonical(event) != body
            ):
                raise InvalidEvent()
            return event
        except (KeyError, TypeError, ValueError, InvalidSignature, ValidationError) as exc:
            raise InvalidEvent() from exc


def connect(settings: Settings):
    params = pika.URLParameters(settings.amqp_url.get_secret_value())
    params.heartbeat = 30
    params.blocked_connection_timeout = 5
    params.socket_timeout = 5
    params.stack_timeout = 10
    connection = pika.BlockingConnection(params)
    channel = connection.channel()
    channel.confirm_delivery()
    channel.basic_qos(prefetch_count=1)
    return connection, channel


def publish(channel, exchange, routing_key, body, headers, event_id):
    confirmed = channel.basic_publish(
        exchange=exchange,
        routing_key=routing_key,
        body=body,
        mandatory=True,
        properties=pika.BasicProperties(
            content_type="application/json", delivery_mode=2, message_id=event_id, headers=headers
        ),
    )
    if confirmed is False:
        raise RuntimeError("Publication not confirmed")


def publish_one(engine, channel, signatures, settings, *, now=None):
    """Lock one local record; confirm first, commit second. A crash can cause a duplicate."""
    now = now or datetime.now(UTC)
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(Outbox)
            .where(
                Outbox.status == "pending",
                Outbox.available_at <= now,
            )
            .order_by(Outbox.available_at, Outbox.event_id)
            .with_for_update(skip_locked=True)
        )
        if row is None:
            return False
        row.attempts += 1
        try:
            event = EventEnvelope.model_validate(row.envelope)
            body, headers = signatures.sign(event)
            publish(
                channel,
                f"events.{settings.service_name}",
                event.event_type,
                body,
                headers,
                str(event.event_id),
            )
        except (InvalidEvent, ValidationError):
            row.status = "dead"
        except Exception:
            row.status = "dead" if row.attempts >= settings.event_max_attempts else "pending"
            row.available_at = now + timedelta(
                seconds=min(300, settings.event_retry_delay_seconds * 2 ** (row.attempts - 1))
            )
        else:
            row.status = "published"
            row.published_at = now
        return True


class SignedConsumer:
    service: str

    def __init__(self, engine, signatures, settings):
        if settings.service_name != self.service or signatures.service != self.service:
            raise ValueError("Consumer signing identity does not match service")
        self.engine, self.signatures, self.settings = engine, signatures, settings

    def __call__(self, channel, method, properties, body):
        headers = dict(properties.headers or {})
        try:
            event = self.signatures.verify(body, headers, properties.message_id)
            handler = self.handler(event)
            if method.exchange not in {f"events.{event.producer}", f"incoming.{self.service}"}:
                raise InvalidEvent()
        except InvalidEvent:
            # Never persist attacker-provided payloads or exception text into a diagnostic queue.
            self.move(channel, method, b'{"code":"invalid_event"}', {}, None, "dead")
            return
        try:
            with Session(self.engine) as session, session.begin():
                handler(session, event)
        except HTTPException as exc:
            if exc.status_code >= 500:
                self.retry(channel, method, body, headers, event)
                return
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

    def retry(self, channel, method, body, headers, event):
        attempt = (
            headers.get("hr-attempt", 0) if method.exchange == f"incoming.{self.service}" else 0
        )
        if not isinstance(attempt, int) or isinstance(attempt, bool) or not 0 <= attempt <= 20:
            attempt = self.settings.event_max_attempts
        attempt += 1
        target = "dead" if attempt >= self.settings.event_max_attempts else "retry"
        self.move(
            channel,
            method,
            body,
            headers | {"hr-attempt": attempt, "hr-error": "processing_failed"},
            str(event.event_id),
            target,
        )

    def move(self, channel, method, body, headers, event_id, target):
        # If republishing fails, let the connection close with the original unacked.
        publish(channel, f"{target}.{self.service}", self.service, body, headers, event_id)
        channel.basic_ack(delivery_tag=method.delivery_tag)


class PrivacyConsumer(SignedConsumer):
    service = "privacy"

    def handler(self, event):
        if event.producer == "hiring" and event.event_type == "hiring.invitation_accepted.v1":
            return process_accepted_invitation
        if (
            event.producer in SERVICES
            and event.producer != "privacy"
            and event.event_type
            in {
                f"{event.producer}.data_deleted.v1",
                f"{event.producer}.data_restricted.v1",
            }
        ):
            return process_deletion_ack
        raise InvalidEvent()


class CandidateConsumer(SignedConsumer):
    service = "candidate"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.confirmed_grade_access import ConfirmedGradeAccess

        self.access = ConfirmedGradeAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        if (
            event.producer == "assessment"
            and event.event_type == "assessment.grade_decision_recorded.v1"
        ):
            from reverse_hr.domains.candidate_grades import process_grade_decision

            return lambda session, event: process_grade_decision(session, event, self.access)
        raise InvalidEvent()


class EmployerConsumer(SignedConsumer):
    service = "employer"

    def handler(self, event):
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_employer_deletion
        raise InvalidEvent()


class AssessmentConsumer(SignedConsumer):
    service = "assessment"

    def handler(self, event):
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_assessment_deletion
        raise InvalidEvent()


class WorkspaceConsumer(SignedConsumer):
    service = "coding-workspace"

    def handler(self, event):
        if event.producer == "code-runner" and event.event_type in {
            "code-runner.run_accepted.v1",
            "code-runner.run_diagnosed.v1",
            "code-runner.run_started.v1",
            "code-runner.run_finished.v1",
            "code-runner.run_cancelled.v1",
        }:
            from reverse_hr.domains.coding_workspace import process_runner_event

            return process_runner_event
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_workspace_deletion
        raise InvalidEvent()


class RunnerConsumer(SignedConsumer):
    service = "code-runner"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.runner_exchange import ManifestAccess

        self.access = ManifestAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        from reverse_hr.domains.code_runner import process_deletion_request, process_run_request

        if (
            event.producer == "coding-workspace"
            and event.event_type == "coding-workspace.run_requested.v1"
        ):
            return lambda session, event: process_run_request(session, event, self.access)
        if event.producer == "assessment" and event.event_type == "assessment.stage_submitted.v1":
            from reverse_hr.submitted_runner import process_submission

            return lambda session, event: process_submission(session, event, self.access)
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        raise InvalidEvent()


class EvaluationConsumer(SignedConsumer):
    service = "evaluation"

    def __init__(self, engine, signatures, settings):
        super().__init__(engine, signatures, settings)
        from reverse_hr.processing_access import ProcessingAccess

        self.access = ProcessingAccess(settings)
        self.access._signatures = signatures

    def handler(self, event):
        from reverse_hr.domains.evaluation import process_deletion_request, process_submission

        if event.producer == "assessment" and event.event_type == "assessment.stage_submitted.v1":
            return lambda session, event: process_submission(session, event, self.access)
        if event.producer == "privacy" and event.event_type == "privacy.deletion_requested.v1":
            return process_deletion_request
        raise InvalidEvent()
