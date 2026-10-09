"""Candidate-confirmed declarations and a separate trusted grade in PDF exports."""

from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from reverse_hr.achievement_contracts import ResumeAchievement
from reverse_hr.contracts import Contract, Grade, ProfileUpdate
from reverse_hr.market_contracts import ContactsCommand, Skills


class ResumeFields(ProfileUpdate, Skills):
    summary: str = Field(default="", max_length=2000)
    experience: list[str] = Field(default_factory=list, max_length=20)
    education: list[str] = Field(default_factory=list, max_length=20)
    contacts: ContactsCommand | None = None

    @field_validator("experience", "education")
    @classmethod
    def bounded(cls, values):
        if any(not isinstance(v, str) or not 1 <= len(v) <= 1000 for v in values):
            raise ValueError("Invalid resume section")
        return values


class ResumeConfirmation(ResumeFields):
    profile_version: int = Field(strict=True, ge=0)


class ExtractedPDF(Contract):
    text: str = Field(max_length=40000)
    pages: int = Field(strict=True, ge=1, le=10)
    ocr_pages: list[int] = Field(default_factory=list, max_length=10)
    extractor: Literal["isolated-pdf-v1"] = "isolated-pdf-v1"

    @model_validator(mode="after")
    def valid_pages(self):
        if len(set(self.ocr_pages)) != len(self.ocr_pages) or any(
            not 1 <= page <= self.pages for page in self.ocr_pages
        ):
            raise ValueError("Invalid OCR pages")
        return self


class PDFData(Contract):
    variant: Literal["full", "anonymous"]
    name: str = Field(min_length=1, max_length=150)
    specialization: str = Field(max_length=100)
    declared_grade: Grade
    demo: Literal[True] = True
    confirmed_grade: Grade | None
    declared_skills: list[str] = Field(max_length=50)
    summary: str = Field(max_length=2000)
    experience: list[str] = Field(max_length=20)
    education: list[str] = Field(max_length=20)
    achievements: list[ResumeAchievement] = Field(default_factory=list, max_length=50)
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=30)

    @field_validator("experience", "education", "declared_skills")
    @classmethod
    def bounded(cls, values):
        if any(len(value) > 1000 for value in values):
            raise ValueError("Invalid section")
        return values

    @model_validator(mode="after")
    def anonymous_contacts(self):
        if self.variant == "anonymous" and (self.email or self.phone):
            raise ValueError("Anonymous PDF cannot contain contacts")
        return self


class ResumePublication(Contract):
    published: bool = Field(strict=True)
    consent_id: UUID | None = None

    @model_validator(mode="after")
    def permission(self):
        if self.published != (self.consent_id is not None):
            raise ValueError("Resume publication requires its own consent")
        return self
