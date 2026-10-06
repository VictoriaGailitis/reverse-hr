import hashlib
import json
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Header, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from reverse_hr.db import IdempotencyRecord

CommandKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]
ExpectedVersion = Annotated[str, Header(alias="If-Match", pattern=r'^"[1-9][0-9]*"$')]


def execute(
    engine, actor, operation, key, payload, handler, status=200, *, guard=None, present=None
):
    """Reserve command key, apply domain change, and persist response in one transaction."""
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
    query = select(IdempotencyRecord).where(
        IdempotencyRecord.actor_id == str(actor),
        IdempotencyRecord.operation == operation,
        IdempotencyRecord.key == key,
    )

    def response(session, result, code):
        result = present(session, result) if present else result
        return JSONResponse(result, status_code=code)

    def replay(session, record):
        if record.request_hash != digest:
            raise HTTPException(409)
        return response(session, json.loads(record.response), record.status_code)

    try:
        with Session(engine) as session, session.begin():
            if guard:
                guard(session)
            record = session.scalar(query)
            if record:
                return replay(session, record)
            record = IdempotencyRecord(
                actor_id=str(actor),
                operation=operation,
                key=key,
                request_hash=digest,
                response="{}",
                status_code=0,
                created_at=datetime.now(UTC),
            )
            session.add(record)
            session.flush()  # Concurrent requests compete for the unique key before any effect.
            result = handler(session)
            record.response = json.dumps(result)
            record.status_code = status
            rendered = response(session, result, status)
        return rendered
    except IntegrityError as exc:
        with Session(engine) as session, session.begin():
            if guard:
                guard(session)
            record = session.scalar(query)
            if record:
                return replay(session, record)
        raise HTTPException(409) from exc
    except OperationalError as exc:
        raise HTTPException(503) from exc
