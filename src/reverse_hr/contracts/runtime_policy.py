"""Explicit operator-approved runtime identities; empty by default."""

from datetime import datetime, timedelta
from uuid import UUID

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract


class TrustedRuntime(Contract):
    policy_id: UUID
    node_id: UUID
    fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
    approved_at: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def bounded(self):
        if (
            self.approved_at.tzinfo is None
            or self.expires_at.tzinfo is None
            or not self.approved_at < self.expires_at <= self.approved_at + timedelta(days=7)
        ):
            raise ValueError("Runtime policy must have a timezone-aware lifetime up to seven days")
        return self
