"""Private immutable task-suite pins; no hidden test bodies in candidate DTOs."""

from uuid import UUID

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.suite_pin import SuitePin
from reverse_hr.contracts.test_suites import digest


class TaskSuiteSelection(Contract):
    revision_id: UUID
    task_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    suite_id: UUID
    validation_id: UUID


class PlanSuitePin(Contract):
    position: int = Field(ge=0, le=19, strict=True)
    revision_id: UUID
    task_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    pin: SuitePin
    validation_id: UUID
    verdict_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    attestation_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    node_id: UUID
    policy_id: UUID

    @model_validator(mode="after")
    def bound(self):
        if self.revision_id != self.pin.revision_id:
            raise ValueError("Suite revision differs from stage")
        return self


class SessionSuitePin(PlanSuitePin):
    stage_id: UUID


class PlanPins(Contract):
    pins: list[PlanSuitePin] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique(self):
        if len({pin.position for pin in self.pins}) != len(self.pins):
            raise ValueError("Duplicate pinned stage position")
        return self


class SessionPins(Contract):
    pins: list[SessionSuitePin] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def unique(self):
        if len({pin.position for pin in self.pins}) != len(self.pins) or len(
            {pin.stage_id for pin in self.pins}
        ) != len(self.pins):
            raise ValueError("Duplicate pinned stage")
        return self


def stored_pins(row, *, for_session=False):
    container = SessionPins if for_session else PlanPins
    result = container(pins=row.test_pins or [])
    if (row.test_pins_digest is None and result.pins) or (
        row.test_pins_digest is not None and digest(result) != row.test_pins_digest
    ):
        raise ValueError("Corrupted private test pins")
    return result.pins
