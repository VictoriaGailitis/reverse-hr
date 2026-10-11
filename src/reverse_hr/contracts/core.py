"""Version-one business DTOs. Proposed contracts, not implemented API routes."""

from enum import StrEnum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Grade(StrEnum):
    junior = "junior"
    middle = "middle"
    senior = "senior"
    lead = "lead"


class SessionStatus(StrEnum):
    created = "created"
    preflight = "preflight"
    in_progress = "in_progress"
    submitted = "submitted"
    evaluating = "evaluating"
    review_pending = "review_pending"
    completed = "completed"
    technical_failure = "technical_failure"


class InvitationStatus(StrEnum):
    draft = "draft"
    sent = "sent"
    viewed = "viewed"
    accepted = "accepted"
    declined = "declined"
    expired = "expired"
    revoked = "revoked"


class SpecializationChoice(Contract):
    specialization: str = Field(min_length=1, max_length=100)
    declared_grade: Grade


class SpecializationProfile(SpecializationChoice):
    confirmed_grade: Grade | None = None


class ProfileUpdate(Contract):
    display_name: str = Field(min_length=1, max_length=100)
    specialization: str = Field(min_length=1, max_length=100)
    declared_grade: Grade
    additional_specializations: list[SpecializationChoice] = Field(
        default_factory=list, max_length=9
    )

    @model_validator(mode="after")
    def unique_specializations(self):
        names = [
            self.specialization,
            *(item.specialization for item in self.additional_specializations),
        ]
        normalized = [name.strip().casefold() for name in names]
        if any(not name for name in normalized) or len(set(normalized)) != len(normalized):
            raise ValueError("Specializations must be nonempty and unique")
        self.specialization = self.specialization.strip()
        for item in self.additional_specializations:
            item.specialization = item.specialization.strip()
        return self


class Profile(ProfileUpdate):
    candidate_id: UUID
    confirmed_grade: Grade | None = None
    version: int = Field(ge=1)
    specializations: list[SpecializationProfile] = Field(default_factory=list, max_length=10)


class ConsentCommand(Contract):
    purpose: Literal[
        "assessment",
        "recording",
        "profile_publication",
        "ats_export",
        "achievement_import",
        "achievement_publication",
        "contact_disclosure",
        "company_result_disclosure",
        "company_task_subscription",
        "task_recommendations",
        "resume_publication",
        "external_service_notifications",
        "external_marketing_notifications",
    ]
    document_version: str = Field(min_length=1, max_length=100)


class Consent(ConsentCommand):
    consent_id: UUID
    status: Literal["active", "revoked"]
    version: int = Field(ge=1)


class SessionCommand(Contract):
    plan_version_id: UUID
    declared_grade: Grade


class AssessmentSession(SessionCommand):
    session_id: UUID
    status: SessionStatus
    version: int = Field(ge=1)


class ReviewCommand(Contract):
    outcome: Literal["pass", "fail", "needs_evidence"]
    reason: str = Field(min_length=1, max_length=2000)
    evidence_ids: list[UUID] = Field(min_length=1)


class GradeDecision(Contract):
    decision_id: UUID
    confirmed_grade: Grade | None
    status: Literal["confirmed", "unchanged", "review_pending"]
    version: int = Field(ge=1)


class SalaryRange(Contract):
    currency: Literal["RUB"] = "RUB"
    period: Literal["month"] = "month"
    tax_basis: Literal["gross", "net"]
    minimum: int = Field(gt=0)
    maximum: int = Field(gt=0)

    @model_validator(mode="after")
    def check_bounds(self):
        if self.maximum < self.minimum:
            raise ValueError("Salary maximum must be at least minimum")
        return self


class HiringNeedCommand(Contract):
    organization_id: UUID
    specialization: str = Field(min_length=1, max_length=100)
    confirmed_grade: Grade
    required_skills: list[str] = Field(max_length=50)


class HiringNeed(HiringNeedCommand):
    need_id: UUID
    version: int = Field(ge=1)


class Match(Contract):
    candidate_id: UUID
    confirmed_grade: Grade
    evidence_ids: list[UUID]
    explanation: str
    ranking_version: str
    demo: bool


class InvitationCommand(Contract):
    organization_id: UUID
    candidate_id: UUID
    description: str = Field(min_length=1, max_length=5000)
    employer_contact: str = Field(min_length=1, max_length=300)
    salary: SalaryRange


class Invitation(InvitationCommand):
    invitation_id: UUID
    status: InvitationStatus
    version: int = Field(ge=1)
    contact_access: Literal["pending", "granted", "revoked", "not_granted"]


class ContactView(Contract):
    candidate_id: UUID
    organization_id: UUID
    grant_id: UUID
    email: str
    phone: str | None


class InvitationAcceptanceCommand(Contract):
    disclosure_consent_id: UUID


class ExportCommand(Contract):
    candidate_id: UUID
    organization_id: UUID
    grant_id: UUID


class ExportJob(Contract):
    export_id: UUID
    status: Literal["queued", "sending", "delivered", "failed", "blocked"]
