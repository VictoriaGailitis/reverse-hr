"""Erasure is atomic with a persistent local anti-resurrection tombstone and ACK."""

from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import delete

from reverse_hr.db import IdempotencyRecord, Outbox, consume_once, enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.market_state import lock


def erase(session, event, service, subject_model, scrub):
    if (
        event.producer != "privacy"
        or event.event_type != "privacy.deletion_requested.v1"
        or set(event.payload) != {"candidate_id", "request_id"}
        or event.aggregate_id != event.payload["request_id"]
        or event.aggregate_version != 1
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = str(event.payload["candidate_id"])
        row = lock(session, subject_model, subject, allow_blocked=True)
        request_id = str(event.payload["request_id"])
        if row.request_id and row.request_id != request_id:
            raise HTTPException(409)
        scrub(subject)
        session.execute(
            delete(IdempotencyRecord).where(
                (IdempotencyRecord.actor_id == subject)
                | IdempotencyRecord.response.contains(subject)
            )
        )
        session.execute(
            delete(Outbox).where(
                Outbox.envelope["payload"]["candidate_id"].as_string() == subject,
                Outbox.envelope["event_type"].as_string().not_in([f"{service}.data_deleted.v1"]),
            )
        )
        first = row.request_id is None
        row.blocked, row.request_id = True, request_id
        if first:
            enqueue(
                session,
                EventEnvelope(
                    producer=service,
                    event_type=f"{service}.data_deleted.v1",
                    correlation_id=event.correlation_id,
                    aggregate_id=event.aggregate_id,
                    aggregate_version=1,
                    payload=event.payload,
                ),
            )

    return consume_once(session, service + ".deletion_request", event, apply)
