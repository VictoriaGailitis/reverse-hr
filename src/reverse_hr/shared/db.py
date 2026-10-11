from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, Integer, String, Text, UniqueConstraint, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from reverse_hr.contracts.events import EventEnvelope


class Base(DeclarativeBase):
    pass


class Outbox(Base):
    __tablename__ = "outbox"
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    envelope: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Inbox(Base):
    __tablename__ = "inbox"
    consumer: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class IdempotencyRecord(Base):
    __tablename__ = "idempotency_records"
    __table_args__ = (UniqueConstraint("actor_id", "operation", "key"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(100))
    operation: Mapped[str] = mapped_column(String(150))
    key: Mapped[str] = mapped_column(String(128))
    request_hash: Mapped[str] = mapped_column(String(64))
    response: Mapped[str] = mapped_column(Text)
    status_code: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def make_engine(url: str):
    options = (
        {"check_same_thread": False}
        if url.startswith("sqlite:")
        else {
            "connect_timeout": 3,
            "options": "-c statement_timeout=3000",
        }
    )
    return create_engine(url, pool_pre_ping=True, connect_args=options)


def enqueue(session: Session, event: EventEnvelope) -> None:
    """Caller commits this insert together with its own business change."""
    session.add(
        Outbox(
            event_id=str(event.event_id),
            envelope=event.model_dump(mode="json"),
            available_at=datetime.now(UTC),
        )
    )


def consume_once(session: Session, consumer: str, event: EventEnvelope, handler) -> bool:
    """Run within a caller-owned transaction; handler must only change this DB.

    Concurrent duplicate inserts fail the unique key and roll back both changes;
    transport should retry, then the existing record causes a no-op.
    """
    key = (consumer, str(event.event_id))
    if session.get(Inbox, key):
        return False
    session.add(Inbox(consumer=consumer, event_id=key[1], processed_at=datetime.now(UTC)))
    session.flush()
    handler(session, event)
    return True
