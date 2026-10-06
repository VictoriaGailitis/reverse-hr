from datetime import UTC, datetime
from typing import Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventEnvelope(BaseModel):
    """Payload contains references only. Sensitive artifacts stay with their owner."""

    model_config = ConfigDict(extra="forbid")
    event_id: UUID = Field(default_factory=uuid4)
    schema_version: Literal[1] = 1
    event_type: str = Field(pattern=r"^[a-z][a-z0-9-]*\.[a-z_]+\.v1$")
    producer: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    correlation_id: UUID
    aggregate_id: UUID
    aggregate_version: int = Field(ge=1)
    payload: dict[str, UUID]
