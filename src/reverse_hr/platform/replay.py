"""Local administrative outbox replay with OIDC/MFA and a persisted command record."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import update

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.platform.settings import Settings
from reverse_hr.shared.auth import TokenVerifier
from reverse_hr.shared.commands import execute
from reverse_hr.shared.db import Outbox, make_engine
from reverse_hr.shared.event_transport import Signatures


def replay_outbox(engine, principal, event_id, key, reason, signatures):
    principal.require("technical_admin", mfa=True)
    if not 1 <= len(reason.strip()) <= 1000:
        raise HTTPException(422)

    def change(session):
        row = session.get(Outbox, str(event_id))
        if row is None:
            raise HTTPException(404)
        try:
            signatures.sign(EventEnvelope.model_validate(row.envelope))
        except Exception as exc:
            raise HTTPException(409) from exc
        previous_attempts = row.attempts
        changed = session.execute(
            update(Outbox)
            .where(
                Outbox.event_id == str(event_id),
                Outbox.status == "dead",
            )
            .values(status="pending", attempts=0, available_at=datetime.now(UTC), published_at=None)
        )
        if changed.rowcount != 1:
            raise HTTPException(409)
        return {
            "event_id": str(event_id),
            "status": "pending",
            "reason": reason,
            "previous_attempts": previous_attempts,
            "operator_id": str(principal.subject),
        }

    # Persist actor, reason, time and effect with the change. A repeated key is a no-op.
    return execute(
        engine,
        principal.subject,
        "admin:outbox_replay",
        str(key),
        {"event_id": str(event_id), "reason": reason},
        change,
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("event_id", type=UUID)
    parser.add_argument("--key", type=UUID, required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    args = parser.parse_args()
    settings = Settings()
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        principal = TokenVerifier(settings).verify(args.token_file.read_text().strip())
        response = replay_outbox(
            engine,
            principal,
            args.event_id,
            args.key,
            args.reason,
            Signatures.from_settings(settings),
        )
        result = json.loads(response.body)
        print(f"outbox_replay event_id={result['event_id']} status={result['status']}")
    except HTTPException as exc:
        raise SystemExit(f"Replay refused: status={exc.status_code}") from None
    except Exception:
        raise SystemExit("Replay unavailable; no sensitive diagnostics emitted") from None
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
