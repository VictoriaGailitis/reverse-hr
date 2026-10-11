"""Immutable evidence documents and exact temporal/object citations."""

import hashlib
from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from reverse_hr.contracts.board import BoardDocument
from reverse_hr.contracts.core import Contract
from reverse_hr.contracts.workspace import FilesCommand
from reverse_hr.shared.signing import canonical


def sha(model):
    return hashlib.sha256(canonical(model)).hexdigest()


class Segment(Contract):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    start_ms: int = Field(strict=True, ge=0, le=7200000)
    end_ms: int = Field(strict=True, ge=1, le=7200000)
    text: str = Field(min_length=1, max_length=2000, pattern=r"\S")


class TranscriptDocument(Contract):
    duration_ms: int = Field(strict=True, ge=1, le=7200000)
    language: str = Field(pattern=r"^[a-z]{2,3}(?:-[A-Za-z]{2,8})?$")
    segments: list[Segment] = Field(min_length=1, max_length=500)

    @model_validator(mode="after")
    def ordered(self):
        previous = 0
        keys = set()
        for segment in self.segments:
            if (
                segment.key in keys
                or not previous <= segment.start_ms < segment.end_ms <= self.duration_ms
            ):
                raise ValueError("Invalid transcript timeline")
            previous = segment.end_ms
            keys.add(segment.key)
        if len(canonical(self)) > 262144:
            raise ValueError("Oversized transcript")
        return self


class PracticalSource(Contract):
    snapshot_id: UUID
    format: Literal["voice", "vcv", "whiteboard"]
    digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    board: BoardDocument | None = None
    transcript_id: UUID | None = None
    transcript_digest: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    transcript: TranscriptDocument | None = None

    @model_validator(mode="after")
    def bound(self):
        if self.format == "whiteboard":
            if (
                self.board is None
                or sha(self.board) != self.digest
                or any(
                    value is not None
                    for value in (self.transcript, self.transcript_id, self.transcript_digest)
                )
            ):
                raise ValueError("Invalid board evidence")
        elif (
            self.board is not None
            or self.transcript is None
            or self.transcript_id is None
            or sha(self.transcript) != self.transcript_digest
        ):
            raise ValueError("Invalid transcript evidence")
        return self


Source = FilesCommand | PracticalSource


def source_model(raw):
    if isinstance(raw, (FilesCommand, PracticalSource)):
        return raw
    return (
        FilesCommand.model_validate(raw) if "files" in raw else PracticalSource.model_validate(raw)
    )


def source_digest(raw):
    source = source_model(raw)
    return sha(source) if isinstance(source, FilesCommand) else source.digest


class RecordingCitation(Contract):
    snapshot_id: UUID
    recording_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    transcript_id: UUID
    transcript_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    segment_key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    start_ms: int = Field(strict=True, ge=0, le=7200000)
    end_ms: int = Field(strict=True, ge=1, le=7200000)

    @model_validator(mode="after")
    def range(self):
        if self.end_ms <= self.start_ms:
            raise ValueError("Empty recording citation")
        return self


class BoardCitation(Contract):
    snapshot_id: UUID
    snapshot_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    object_id: UUID
    object_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
