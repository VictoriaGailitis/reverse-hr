from uuid import UUID

from pydantic import Field

from reverse_hr.contracts.core import Contract


class SuitePin(Contract):
    suite_id: UUID
    revision_id: UUID
    content_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    definition_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    runtime_fingerprint: str = Field(pattern=r"^[a-f0-9]{64}$")
