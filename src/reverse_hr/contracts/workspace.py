"""Public data contract; no service persistence or HTTP handlers."""

from pathlib import PurePosixPath

from pydantic import Field, field_validator, model_validator

from reverse_hr.contracts.core import Contract


class File(Contract):
    path: str = Field(min_length=1, max_length=200)
    content: str = Field(max_length=65536)

    @field_validator("path")
    @classmethod
    def safe_path(cls, value):
        if (
            "\\" in value
            or not value.isascii()
            or any(ord(c) < 32 for c in value)
            or PurePosixPath(value).is_absolute()
            or str(PurePosixPath(value)) != value
            or any(part in {".", "..", ""} for part in value.split("/"))
        ):
            raise ValueError("Use a normalized relative path")
        return value


class FilesCommand(Contract):
    files: list[File] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def bounded(self):
        if (
            len({f.path for f in self.files}) != len(self.files)
            or any(len(f.content.encode("utf-8")) > 65536 for f in self.files)
            or sum(len(f.content.encode("utf-8")) for f in self.files) > 262144
        ):
            raise ValueError("Duplicate paths or oversized snapshot")
        return self
