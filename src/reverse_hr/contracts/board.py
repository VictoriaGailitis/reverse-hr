"""Public data contract; no service persistence or HTTP handlers."""

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from reverse_hr.contracts.core import Contract


class Point(Contract):
    x: float = Field(ge=0, le=10000, allow_inf_nan=False)
    y: float = Field(ge=0, le=10000, allow_inf_nan=False)


class Shape(Contract):
    id: UUID
    kind: Literal["stroke", "rectangle", "ellipse", "text"]
    points: list[Point] = Field(min_length=1, max_length=500)
    text: str = Field(default="", max_length=2000)
    color: str = Field(default="#000000", pattern=r"^#[0-9a-fA-F]{6}$")
    width: int = Field(default=2, ge=1, le=30)

    @model_validator(mode="after")
    def geometry(self):
        if (
            (self.kind in {"rectangle", "ellipse"} and len(self.points) != 2)
            or (self.kind == "text" and len(self.points) != 1)
            or (self.kind != "text" and self.text)
        ):
            raise ValueError("Invalid shape geometry")
        return self


class BoardDocument(Contract):
    state: list[Shape] = Field(max_length=100)
