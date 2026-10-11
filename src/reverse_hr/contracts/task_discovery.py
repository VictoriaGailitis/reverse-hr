"""Public recommendation metadata only; no hidden solutions or test evidence."""

from uuid import UUID

from pydantic import Field, field_validator

from reverse_hr.contracts.core import Contract, Grade
from reverse_hr.contracts.market_contracts import Skills


class TaskOffer(Contract):
    version_id: UUID
    name: str = Field(min_length=1, max_length=200)
    specialization: str = Field(min_length=1, max_length=100)
    grade: Grade
    stack_tags: list[str] = Field(max_length=20)
    format: str = Field(pattern=r"^(code|sql|voice|vcv|whiteboard)$")

    @field_validator("stack_tags")
    @classmethod
    def clean(cls, values):
        return Skills(declared_skills=values).declared_skills


class TaskCatalog(Contract):
    items: list[TaskOffer] = Field(max_length=3)
    next_cursor: UUID | None


class TaskNotice(Contract):
    notice_id: UUID
    recipient_id: UUID
    kind: str = Field(pattern="^task_available$")
    category: str = Field(pattern="^marketing$")
