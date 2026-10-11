"""Minimal service-owned recruitment DTOs; contacts never enter search cards."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from reverse_hr.contracts.core import Contract, Grade, SalaryRange
from reverse_hr.contracts.matching_conditions import CandidatePreferences, EmploymentConditions
from reverse_hr.contracts.qualification_contracts import QualificationEvidence
from reverse_hr.protocols.processing_access import ProcessingRequest


class Skills(Contract):
    declared_skills: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("declared_skills")
    @classmethod
    def clean(cls, values):
        result = [v.strip().casefold() for v in values]
        if any(not v or len(v) > 64 or any(ord(c) < 32 for c in v) for v in result) or len(
            set(result)
        ) != len(result):
            raise ValueError("Invalid or duplicate skills")
        return sorted(result)


class PublicationCommand(Skills):
    published: bool = Field(strict=True)
    consent_id: UUID | None = None

    @model_validator(mode="after")
    def permission(self):
        if self.published != (self.consent_id is not None):
            raise ValueError("Publication requires its own consent")
        return self


class CandidateCard(Skills):
    candidate_id: UUID
    display_name: str = Field(min_length=1, max_length=100)
    specialization: str = Field(min_length=1, max_length=100)
    confirmed_grade: Grade | None
    decision_id: UUID | None
    version: int = Field(strict=True, ge=1)
    demo: Literal[True] = True
    qualification: QualificationEvidence | None = None
    preferences: CandidatePreferences | None = None


class ContactsCommand(Contract):
    email: str = Field(min_length=3, max_length=320, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    phone: str | None = Field(default=None, min_length=3, max_length=30, pattern=r"^\+?[0-9 ()-]+$")


class NeedCommand(Contract):
    conditions: EmploymentConditions | None = None
    organization_id: UUID
    specialization: str = Field(min_length=1, max_length=100)
    confirmed_grade: Grade
    required_skills: list[str] = Field(default_factory=list, max_length=50)
    status: Literal["draft", "published", "closed"] = "draft"

    @field_validator("required_skills")
    @classmethod
    def skills(cls, values):
        return Skills(declared_skills=values).declared_skills


class NeedView(NeedCommand):
    need_id: UUID
    created_by: UUID
    version: int = Field(ge=1)


class MarketRequest(ProcessingRequest):
    specialization: str | None = Field(
        default=None, min_length=1, max_length=100, exclude_if=lambda v: v is None
    )
    requester: Literal[
        "achievements",
        "integration",
        "demo-ats",
        "candidate",
        "matching",
        "hiring",
        "notification",
        "assessment",
        "evaluation",
    ]
    purpose: Literal[
        "profile",
        "task-catalog",
        "task-notice",
        "membership",
        "affiliation",
        "content-membership",
        "need",
        "purpose-permission",
        "contact-permission",
        "resume-permission",
        "company-result-permission",
        "company-notice",
        "appeal-notice",
        "contacts",
        "notice",
    ]
    catalog_after: UUID | None = Field(default=None, exclude_if=lambda v: v is None)
    catalog_version_id: UUID | None = Field(default=None, exclude_if=lambda v: v is None)
    assignment_id: UUID | None = None
    result_grant_id: UUID | None = None
    organization_id: UUID | None = None
    actor_id: UUID | None = None
    notice_id: UUID | None = None
    need_id: UUID | None = None
    invitation_id: UUID | None = None
    consent_id: UUID | None = None
    consent_purpose: (
        Literal[
            "achievement_import",
            "achievement_publication",
            "ats_export",
            "profile_publication",
            "contact_disclosure",
            "company_task_subscription",
            "task_recommendations",
            "resume_publication",
            "external_service_notifications",
            "external_marketing_notifications",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def refs(self):
        if self.specialization is not None and self.purpose != "profile":
            raise ValueError("Specialization applies only to profile disclosure")
        if (
            self.catalog_after is not None or self.catalog_version_id is not None
        ) and self.purpose != "task-catalog":
            raise ValueError("Catalog references apply only to task catalog")
        if self.catalog_after is not None and self.catalog_version_id is not None:
            raise ValueError("Cannot mix exact catalog lookup and pagination")
        needed = {
            "profile": set(),
            "task-catalog": set(),
            "task-notice": {"notice_id"},
            "company-result-permission": {"assignment_id", "organization_id", "result_grant_id"},
            "notice": {"notice_id"},
            "company-notice": {"notice_id"},
            "appeal-notice": {"notice_id"},
            "membership": {"organization_id", "actor_id"},
            "affiliation": {"organization_id", "actor_id"},
            "content-membership": {"organization_id", "actor_id"},
            "need": {"organization_id", "actor_id", "need_id"},
            "purpose-permission": {"consent_id", "consent_purpose"},
            "contact-permission": {"organization_id", "invitation_id"},
            "contacts": {"organization_id", "invitation_id", "actor_id"},
            "resume-permission": {"organization_id", "invitation_id", "actor_id"},
        }[self.purpose]
        actual = {
            k
            for k in (
                "assignment_id",
                "result_grant_id",
                "notice_id",
                "organization_id",
                "actor_id",
                "need_id",
                "invitation_id",
                "consent_id",
                "consent_purpose",
            )
            if getattr(self, k) is not None
        }
        if actual != needed or (
            self.purpose in {"membership", "affiliation", "content-membership", "need"}
            and self.candidate_id != self.actor_id
        ):
            raise ValueError("Invalid recruitment request bindings")
        return self


class MarketReceipt(MarketRequest):
    allowed: bool = Field(strict=True)
    revision: int = Field(default=0, strict=True, ge=0)
    data: dict | None = None

    @model_validator(mode="after")
    def coherent(self):
        if self.allowed != (self.data is not None):
            raise ValueError("Invalid receipt")
        return self


class InvitationCreate(Contract):
    conditions: EmploymentConditions | None = None
    organization_id: UUID
    candidate_id: UUID
    description: str = Field(min_length=1, max_length=5000, pattern=r"\S")
    employer_contact: str = Field(min_length=1, max_length=300, pattern=r"\S")
    salary: SalaryRange
    expires_in_days: int = Field(default=14, strict=True, ge=1, le=90)

    @model_validator(mode="after")
    def salary_conditions(self):
        if (
            self.conditions
            and self.conditions.salary
            and self.conditions.salary.model_dump() != self.salary.model_dump()
        ):
            raise ValueError("Invitation and matching salary must agree")
        return self


class InvitationView(Contract):
    conditions: EmploymentConditions | None = None
    invitation_id: UUID
    organization_id: UUID
    candidate_id: UUID
    description: str
    employer_contact: str
    salary: SalaryRange
    status: Literal["draft", "sent", "viewed", "accepted", "declined", "revoked", "expired"]
    version: int
    expires_at: datetime


class Acceptance(Contract):
    disclosure_consent_id: UUID


class NoticeView(Contract):
    creator_id: UUID
    candidate_id: UUID
    author_id: UUID
    notice_id: UUID
    recipient_id: UUID
    invitation_id: UUID | None = None
    application_id: UUID | None = None
    kind: Literal[
        "invitation_sent",
        "invitation_accepted",
        "invitation_declined",
        "invitation_revoked",
        "dialog_message",
        "application_submitted",
        "application_status_changed",
    ]

    @model_validator(mode="after")
    def notice_scope(self):
        application = self.kind.startswith("application_")
        if application != (self.application_id is not None) or application == (
            self.invitation_id is not None
        ):
            raise ValueError("Invalid notice scope")
        return self


class CompanyNoticeView(Contract):
    notice_id: UUID
    assignment_id: UUID
    organization_id: UUID
    candidate_id: UUID
    creator_id: UUID
    author_id: UUID
    recipient_id: UUID
    kind: Literal["new_assignment", "deadline_reminder", "result_ready"]
    category: Literal["service", "marketing"]


class AppealNoticeView(Contract):
    notice_id: UUID
    appeal_id: UUID
    candidate_id: UUID
    recipient_id: UUID
    author_id: UUID
    kind: Literal["appeal_submitted", "appeal_review_started", "appeal_resolved"]
