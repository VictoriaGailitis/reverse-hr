from datetime import datetime
from uuid import UUID

from pydantic import Field

from reverse_hr.contracts.core import Contract


class ProbeRecord(Contract):
    version: int = Field(default=1, ge=1, le=1, strict=True)
    node_id: UUID
    checked_at: datetime
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    passed: int = Field(ge=12, le=12, strict=True)
