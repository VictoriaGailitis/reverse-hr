"""Original written references, previews and version-pinned generation jobs."""

import hashlib
import re
from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, field_validator, model_validator
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, delete, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract, Grade
from reverse_hr.contracts.test_suites import SuiteDefinition, digest
from reverse_hr.services.assessment.domain.assessment import (
    AssessmentBase,
    Competency,
    Criterion,
    Task,
)
from reverse_hr.services.assessment.domain.assessment_sessions import (
    ReasonCommand,
    SessionView,
    subject_lock,
    utc,
)
from reverse_hr.services.assessment.domain.company_tasks import membership
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute


class GenerationReference(AssessmentBase):
    __tablename__ = "assessment_generation_references"
    __table_args__ = (UniqueConstraint("reference_id", "number"),)
    version_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    reference_id: Mapped[str] = mapped_column(String(36), index=True)
    number: Mapped[int]
    organization_id: Mapped[str | None] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    grading_policy_id: Mapped[str | None] = mapped_column(String(36))
    approved_by: Mapped[str | None] = mapped_column(String(36))
    data: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GenerationPreview(AssessmentBase):
    __tablename__ = "assessment_generation_previews"
    preview_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    specification: Mapped[dict] = mapped_column(JSON)
    digest: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    generation_id: Mapped[str | None] = mapped_column(String(36), unique=True)


class GenerationJob(AssessmentBase):
    __tablename__ = "assessment_generation_jobs"
    generation_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    version_id: Mapped[str] = mapped_column(String(36), index=True)
    author_id: Mapped[str] = mapped_column(String(36), index=True)
    specification: Mapped[dict] = mapped_column(JSON)
    specification_digest: Mapped[str] = mapped_column(String(64))
    model: Mapped[str] = mapped_column(String(200))
    configuration: Mapped[dict] = mapped_column(JSON)
    prompt_digest: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(24))
    attempts: Mapped[int]
    error: Mapped[str | None] = mapped_column(String(100))
    output: Mapped[dict | None] = mapped_column(JSON)
    output_digest: Mapped[str | None] = mapped_column(String(64), index=True)
    revision_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    suite_id: Mapped[str | None] = mapped_column(String(36))
    validation_id: Mapped[str | None] = mapped_column(String(36), unique=True)
    runtime_fingerprint: Mapped[str | None] = mapped_column(String(64))
    plan_version_id: Mapped[str | None] = mapped_column(String(36))
    grade_policy_id: Mapped[str | None] = mapped_column(String(36))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[str | None] = mapped_column(String(36))


class ReferenceCommand(Contract):
    stack_tags: list[str] = Field(default_factory=list, max_length=20, exclude_if=lambda v: not v)

    @field_validator("stack_tags")
    @classmethod
    def clean_stack(cls, values):
        from reverse_hr.contracts.market_contracts import Skills

        return Skills(declared_skills=values).declared_skills

    organization_id: UUID | None = None
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    format: Literal["code", "sql", "vcv", "voice", "whiteboard"]
    specialization: str = Field(min_length=1, max_length=100, pattern=r"\S")
    grade: Grade
    description: str = Field(min_length=20, max_length=12000, pattern=r"\S")
    required_constraints: list[str] = Field(min_length=1, max_length=20)
    allowed_variations: list[str] = Field(min_length=1, max_length=20)
    forbidden_changes: list[str] = Field(min_length=1, max_length=20)
    parameters: dict[str, list[str]] = Field(default_factory=dict, max_length=12)
    competencies: list[Competency] = Field(min_length=1, max_length=20)
    rubric: list[Criterion] = Field(min_length=1, max_length=20)
    duration_seconds: int = Field(strict=True, ge=60, le=3600)
    pool_size: int = Field(default=3, strict=True, ge=1, le=20)
    max_exposures: int = Field(default=100, strict=True, ge=1, le=10000)
    grade_policy_id: UUID | None = None

    @model_validator(mode="after")
    def coherent(self):
        texts = [
            self.name,
            self.description,
            *self.required_constraints,
            *self.allowed_variations,
            *self.forbidden_changes,
        ]
        if any(
            not text.strip() or len(text) > 12000 or re.search(r"https?://|www\.", text, re.I)
            for text in texts
        ):
            raise ValueError("Use original written specifications without external links")
        Task(
            key="generated",
            format=self.format,
            instruction=self.description,
            reference_answer="pending",
            rubric=self.rubric,
            duration_seconds=self.duration_seconds,
        )
        keys = {c.key for c in self.competencies}
        if len(keys) != len(self.competencies) or keys != {c.competency for c in self.rubric}:
            raise ValueError("Reference competencies must exactly cover its rubric")
        if self.format in {"code", "sql"} and not any(
            c.evidence == "test_result" for c in self.rubric
        ):
            raise ValueError("Executable generation requires hidden-test criteria")
        if self.organization_id is not None and self.grade_policy_id is not None:
            raise ValueError("Company references cannot assign platform grades")
        for key, values in self.parameters.items():
            if (
                not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", key)
                or not 1 <= len(values) <= 20
                or len(set(values)) != len(values)
                or any(
                    not value.strip()
                    or len(value) > 200
                    or re.search(r"https?://|www\.", value, re.I)
                    for value in values
                )
            ):
                raise ValueError("Invalid parameter bounds")
        return self


class ReferenceView(ReferenceCommand):
    version_id: UUID
    reference_id: UUID
    number: int
    status: Literal["draft", "published", "retired"]
    version: int
    digest: str


class PreviewCommand(Contract):
    scenario: str = Field(min_length=10, max_length=2000, pattern=r"\S")
    parameters: dict[str, str] = Field(default_factory=dict, max_length=12)


class PreviewView(Contract):
    preview_id: UUID
    version_id: UUID
    specification: dict
    digest: str
    expires_at: datetime


class GenerateCommand(Contract):
    preview_id: UUID
    specification_digest: str = Field(pattern=r"^[a-f0-9]{64}$")


class GenerationView(Contract):
    generation_id: UUID
    version_id: UUID
    status: Literal[
        "pending", "running", "validating", "ready", "rejected", "technical_failure", "cancelled"
    ]
    error: str | None
    task: Task | None = None
    revision_id: UUID | None = None
    plan_version_id: UUID | None = None
    grade_policy_id: UUID | None = None
    attempts: int


class GeneratedBundle(Contract):
    task: Task
    suite: SuiteDefinition | None = None


router = APIRouter(prefix="/v1/assessment-generation", tags=["original-generation"])


def reference_view(row):
    return ReferenceView(
        **(row.data | {"grade_policy_id": row.grading_policy_id}),
        version_id=row.version_id,
        reference_id=row.reference_id,
        number=row.number,
        status=row.status,
        version=row.version,
        digest=row.digest,
    ).model_dump(mode="json")


def job_view(row):
    return GenerationView(
        generation_id=row.generation_id,
        version_id=row.version_id,
        status=row.status,
        error=row.error,
        task=row.output["task"] if row.output else None,
        revision_id=row.revision_id,
        plan_version_id=row.plan_version_id,
        grade_policy_id=row.grade_policy_id,
        attempts=row.attempts,
    ).model_dump(mode="json")


def authorize(request, session, actor, row=None, organization=None):
    organization = row.organization_id if row else organization
    if organization:
        membership(request, actor, organization)
    else:
        actor.require("content_admin", mfa=True)
    owners = {str(actor.subject)} | ({row.author_id, row.approved_by} - {None} if row else set())
    for owner in sorted(owners):
        subject_lock(session, owner)
        request.app.state.processing_access.check(UUID(owner))
    return row


def owned_reference(request, session, actor, version_id):
    row = session.scalar(
        select(GenerationReference)
        .where(GenerationReference.version_id == str(version_id))
        .with_for_update()
    )
    if row is None:
        raise HTTPException(404)
    authorize(request, session, actor, row)
    return row


@router.get("/references", response_model=list[ReferenceView])
def references(
    request: Request, actor: Actor, organization_id: UUID | None = None, limit: int = 50
):
    with Session(request.app.state.engine) as session, session.begin():
        authorize(request, session, actor, organization=organization_id)
        rows = session.scalars(
            select(GenerationReference)
            .where(
                GenerationReference.organization_id
                == (str(organization_id) if organization_id else None)
            )
            .order_by(GenerationReference.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
        return [reference_view(row) for row in rows]


@router.post("/references", response_model=ReferenceView, status_code=201)
def create_reference(
    request: Request, actor: Actor, body: ReferenceCommand, idempotency: CommandKey
):
    def guard(session):
        authorize(request, session, actor, organization=body.organization_id)

    def change(session):
        if body.grade_policy_id:
            raise HTTPException(422, "Bind calibration separately after trial generation")
        row = GenerationReference(
            version_id=str(uuid4()),
            reference_id=str(uuid4()),
            number=1,
            organization_id=str(body.organization_id) if body.organization_id else None,
            author_id=str(actor.subject),
            approved_by=None,
            data=body.model_dump(mode="json"),
            digest=digest(body),
            status="draft",
            version=1,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        return reference_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "generation_reference_create",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
    )


@router.post("/references/{version_id}/versions", response_model=ReferenceView, status_code=201)
def edit_reference(
    request: Request,
    actor: Actor,
    version_id: UUID,
    body: ReferenceCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        owned_reference(request, session, actor, version_id)

    def change(session):
        if body.grade_policy_id:
            raise HTTPException(422, "Bind calibration separately for the new version")
        old = owned_reference(request, session, actor, version_id)
        if (
            old.version != int(if_match.strip('"'))
            or (str(body.organization_id) if body.organization_id else None) != old.organization_id
        ):
            raise HTTPException(409)
        previous = ReferenceCommand.model_validate(old.data)
        if any(
            getattr(body, key) != getattr(previous, key)
            for key in ("format", "specialization", "grade")
        ):
            raise HTTPException(422, "Create a separate reference for another format or level")
        latest = session.scalar(
            select(GenerationReference)
            .where(GenerationReference.reference_id == old.reference_id)
            .order_by(GenerationReference.number.desc())
            .limit(1)
        )
        if latest.version_id != old.version_id:
            raise HTTPException(409, "Edit the latest reference version")
        old.version += 1
        row = GenerationReference(
            version_id=str(uuid4()),
            reference_id=old.reference_id,
            number=old.number + 1,
            organization_id=old.organization_id,
            author_id=str(actor.subject),
            approved_by=None,
            data=body.model_dump(mode="json"),
            digest=digest(body),
            status="draft",
            version=1,
            created_at=datetime.now(UTC),
        )
        session.add(row)
        return reference_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generation_reference_edit:{version_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
    )


@router.post("/references/{version_id}/preview", response_model=PreviewView, status_code=201)
def preview(
    request: Request, actor: Actor, version_id: UUID, body: PreviewCommand, idempotency: CommandKey
):
    def guard(session):
        owned_reference(request, session, actor, version_id)

    def change(session):
        row = owned_reference(request, session, actor, version_id)
        ref = ReferenceCommand.model_validate(row.data)
        if (
            row.status == "retired"
            or set(body.parameters) != set(ref.parameters)
            or any(value not in ref.parameters[key] for key, value in body.parameters.items())
            or re.search(r"https?://|www\.", body.scenario, re.I)
        ):
            raise HTTPException(422, "Scenario and parameters must satisfy the original reference")
        specification = dict(
            reference=ref.model_dump(
                mode="json",
                exclude={"organization_id", "grade_policy_id", "pool_size", "max_exposures"},
            ),
            scenario=body.scenario,
            parameters=body.parameters,
            reference_digest=row.digest,
        )
        sha = hashlib.sha256(
            __import__("json").dumps(specification, sort_keys=True, ensure_ascii=False).encode()
        ).hexdigest()
        item = GenerationPreview(
            preview_id=str(uuid4()),
            version_id=row.version_id,
            author_id=str(actor.subject),
            specification=specification,
            digest=sha,
            expires_at=datetime.now(UTC) + timedelta(minutes=30),
        )
        session.add(item)
        return PreviewView(
            preview_id=item.preview_id,
            version_id=version_id,
            specification=specification,
            digest=sha,
            expires_at=item.expires_at,
        ).model_dump(mode="json")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generation_preview:{version_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
    )


def new_job(settings, reference, author, specification, sha):
    from reverse_hr.services.assessment.generation_gateway import PROMPT

    if (
        not settings.assessment_generation_enabled
        or not settings.assessment_generation_model
        or settings.assessment_generation_config is None
    ):
        raise HTTPException(409, "Generation provider is not configured")
    now = datetime.now(UTC)
    return GenerationJob(
        generation_id=str(uuid4()),
        version_id=reference.version_id,
        author_id=str(author),
        specification=specification,
        specification_digest=sha,
        model=settings.assessment_generation_model,
        configuration=settings.assessment_generation_config.model_dump(mode="json"),
        prompt_digest=hashlib.sha256(PROMPT.encode()).hexdigest(),
        status="pending",
        attempts=0,
        error=None,
        created_at=now,
        available_at=now,
    )


@router.post("/generate", response_model=GenerationView, status_code=202)
def generate(request: Request, actor: Actor, body: GenerateCommand, idempotency: CommandKey):
    def guard(session):
        item = session.get(GenerationPreview, str(body.preview_id))
        if item is None or item.author_id != str(actor.subject):
            raise HTTPException(404)
        owned_reference(request, session, actor, item.version_id)

    def change(session):
        item = session.scalar(
            select(GenerationPreview)
            .where(GenerationPreview.preview_id == str(body.preview_id))
            .with_for_update()
        )
        row = owned_reference(request, session, actor, item.version_id)
        if (
            row.status == "retired"
            or item.generation_id
            or utc(item.expires_at) <= datetime.now(UTC)
            or body.specification_digest != item.digest
            or item.specification["reference_digest"] != row.digest
        ):
            raise HTTPException(409, "Preview is expired, consumed or changed")
        job = new_job(
            request.app.state.settings, row, actor.subject, item.specification, item.digest
        )
        session.add(job)
        item.generation_id = job.generation_id
        return {"generation_id": job.generation_id}

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generation_confirm:{body.preview_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        202,
        guard=guard,
        present=lambda session, result: job_view(
            session.get(GenerationJob, result["generation_id"])
        ),
    )


@router.get("/references/{version_id}/jobs", response_model=list[GenerationView])
def jobs(request: Request, actor: Actor, version_id: UUID):
    with Session(request.app.state.engine) as session, session.begin():
        owned_reference(request, session, actor, version_id)
        return [
            job_view(row)
            for row in session.scalars(
                select(GenerationJob)
                .where(GenerationJob.version_id == str(version_id))
                .order_by(GenerationJob.created_at.desc())
                .limit(50)
            )
        ]


@router.post("/references/{version_id}/publish", response_model=ReferenceView)
def publish(
    request: Request,
    actor: Actor,
    version_id: UUID,
    body: ReasonCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        owned_reference(request, session, actor, version_id)

    def change(session):
        row = owned_reference(request, session, actor, version_id)
        if row.version != int(if_match.strip('"')) or row.status != "draft":
            raise HTTPException(409)
        if (
            session.scalar(
                select(GenerationJob.generation_id).where(
                    GenerationJob.version_id == str(version_id), GenerationJob.status == "ready"
                )
            )
            is None
        ):
            raise HTTPException(409, "A validated trial is required")
        if row.organization_id is None and row.author_id == str(actor.subject):
            raise HTTPException(403, "Independent reference approval required")
        if row.grading_policy_id:
            from reverse_hr.services.assessment.domain.assessment_grades import GradePolicy, Rules

            policy = session.get(GradePolicy, row.grading_policy_id)
            if (
                policy is None
                or policy.status != "approved"
                or policy.calibration is None
                or Rules.model_validate(policy.rules).generation_reference_id != version_id
            ):
                raise HTTPException(
                    409, "A calibrated policy bound to this reference version is required"
                )
        row.status, row.approved_by, row.version = "published", str(actor.subject), row.version + 1
        from reverse_hr.services.assessment.generation_worker import activate

        for job in session.scalars(
            select(GenerationJob).where(
                GenerationJob.version_id == row.version_id, GenerationJob.status == "ready"
            )
        ):
            activate(request, session, job, row)
        for old in session.scalars(
            select(GenerationReference).where(
                GenerationReference.reference_id == row.reference_id,
                GenerationReference.version_id != row.version_id,
                GenerationReference.status == "published",
            )
        ):
            old.status, old.version = "retired", old.version + 1
        return reference_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generation_publish:{version_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=guard,
    )


@router.post("/references/{version_id}/retire", response_model=ReferenceView)
def retire(
    request: Request,
    actor: Actor,
    version_id: UUID,
    body: ReasonCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    def guard(session):
        owned_reference(request, session, actor, version_id)

    def change(session):
        row = owned_reference(request, session, actor, version_id)
        if row.version != int(if_match.strip('"')) or row.status == "retired":
            raise HTTPException(409)
        row.status, row.version = "retired", row.version + 1
        session.execute(
            delete(GenerationPreview).where(GenerationPreview.version_id == row.version_id)
        )
        for job in session.scalars(
            select(GenerationJob).where(
                GenerationJob.version_id == row.version_id,
                GenerationJob.status.in_(["pending", "running", "validating"]),
            )
        ):
            job.status, job.error = "cancelled", "reference_retired"
        return reference_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generation_retire:{version_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=guard,
    )


class PolicyBindingCommand(Contract):
    grade_policy_id: UUID


@router.post("/references/{version_id}/grading-policy", response_model=ReferenceView)
def bind_grading_policy(
    request: Request,
    actor: Actor,
    version_id: UUID,
    body: PolicyBindingCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    actor.require("content_admin", mfa=True)

    def guard(session):
        owned_reference(request, session, actor, version_id)

    def change(session):
        from reverse_hr.services.assessment.domain.assessment_grades import GradePolicy, Rules

        row = owned_reference(request, session, actor, version_id)
        policy = session.get(GradePolicy, str(body.grade_policy_id))
        if (
            row.organization_id
            or row.status != "draft"
            or row.version != int(if_match.strip('"'))
            or policy is None
            or policy.status != "approved"
            or policy.calibration is None
            or policy.plan_version_id
            not in set(
                session.scalars(
                    select(GenerationJob.plan_version_id).where(
                        GenerationJob.version_id == str(version_id), GenerationJob.status == "ready"
                    )
                )
            )
            or Rules.model_validate(policy.rules).generation_reference_id != version_id
        ):
            raise HTTPException(
                409, "Only a calibrated policy scoped to this draft reference may be bound"
            )
        row.grading_policy_id, row.version = str(body.grade_policy_id), row.version + 1
        return reference_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generation_grading_policy:{version_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        guard=guard,
    )


class GeneratedOffer(Contract):
    version_id: UUID
    name: str
    format: str
    specialization: str
    grade: Grade
    duration_seconds: int
    scored: bool


class GeneratedSessionCommand(Contract):
    version_id: UUID
    assessment_consent_id: UUID


@router.get("/offers", response_model=list[GeneratedOffer])
def offers(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        result = []
        for row in session.scalars(
            select(GenerationReference).where(
                GenerationReference.organization_id.is_(None),
                GenerationReference.status == "published",
            )
        ):
            if session.scalar(
                select(GenerationJob.generation_id)
                .where(GenerationJob.version_id == row.version_id, GenerationJob.status == "ready")
                .limit(1)
            ):
                data = row.data
                result.append(
                    GeneratedOffer(
                        version_id=row.version_id,
                        name=data["name"],
                        format=data["format"],
                        specialization=data["specialization"],
                        grade=data["grade"],
                        duration_seconds=data["duration_seconds"],
                        scored=bool(row.grading_policy_id),
                    )
                )
        return result


@router.post("/sessions", status_code=201, response_model=SessionView)
def generated_session(
    request: Request, actor: Actor, body: GeneratedSessionCommand, idempotency: CommandKey
):
    from reverse_hr.services.assessment.domain.assessment_sessions import (
        PracticalSession,
        SessionCommand,
        admit_session,
        guard_session_admission,
        session_view,
    )

    actor.require("candidate")

    def guard(session):
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check_assessment(
            actor.subject, body.assessment_consent_id
        )

    def change(session):
        reference = session.scalar(
            select(GenerationReference)
            .where(GenerationReference.version_id == str(body.version_id))
            .with_for_update()
        )
        if reference is None or reference.status != "published" or reference.organization_id:
            raise HTTPException(409)
        jobs = list(
            session.scalars(
                select(GenerationJob)
                .where(
                    GenerationJob.version_id == reference.version_id,
                    GenerationJob.status == "ready",
                )
                .order_by(GenerationJob.created_at)
            )
        )
        from reverse_hr.services.assessment.domain.assessment_sessions import PracticalSession

        counts = {
            job.plan_version_id: session.query(PracticalSession)
            .filter_by(plan_version_id=job.plan_version_id)
            .count()
            for job in jobs
        }
        for job in sorted(jobs, key=lambda j: (counts[j.plan_version_id], j.generation_id)):
            if counts[job.plan_version_id] >= reference.data["max_exposures"]:
                continue
            command = SessionCommand(
                plan_version_id=job.plan_version_id,
                assessment_consent_id=body.assessment_consent_id,
                grade_policy_id=job.grade_policy_id,
            )
            guard_session_admission(request, actor, command, session)
            row = admit_session(request, actor, command, session)
            return {"session_id": row["session_id"]}
        raise HTTPException(409, "The generation pool is being replenished")

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generated_session:{body.version_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=lambda session, value: session_view(
            session.get(PracticalSession, value["session_id"])
        ),
    )


def admission_guard(session, plan_id, candidate, *, grade_policy_id=None, assignment_id=None):
    from reverse_hr.services.assessment.domain.assessment_sessions import PracticalSession

    job = session.scalar(select(GenerationJob).where(GenerationJob.plan_version_id == str(plan_id)))
    if job is None:
        from reverse_hr.services.assessment.domain.assessment_sessions import PlanVersion

        plan = session.get(PlanVersion, str(plan_id))
        if plan and session.scalar(
            select(GenerationJob.generation_id)
            .where(GenerationJob.revision_id.in_(plan.revision_ids))
            .limit(1)
        ):
            raise HTTPException(409, "Use the canonical generated plan and its issuance limits")
        return
    if (str(grade_policy_id) if grade_policy_id else None) != job.grade_policy_id:
        raise HTTPException(409, "Use the generated variant's pinned grade policy")
    ref = session.scalar(
        select(GenerationReference)
        .where(GenerationReference.version_id == job.version_id)
        .with_for_update()
    )
    if ref is None or ref.status != "published" or job.status != "ready":
        raise HTTPException(409, "Generated reference is inactive")
    if ref.organization_id:
        from reverse_hr.services.assessment.domain.company_assignments import CompanyAssignment

        assignment = session.get(CompanyAssignment, str(assignment_id)) if assignment_id else None
        if (
            assignment is None
            or assignment.candidate_id != str(candidate)
            or assignment.plan_version_id != str(plan_id)
            or assignment.organization_id != ref.organization_id
            or assignment.status != "assigned"
            or utc(assignment.expires_at) <= datetime.now(UTC)
        ):
            raise HTTPException(409, "Accept the company assignment with a permitted result grant")
    if (
        session.query(PracticalSession).filter_by(plan_version_id=str(plan_id)).count()
        >= ref.data["max_exposures"]
    ):
        raise HTTPException(409, "Generated variant exposure limit reached")
    plans = (
        select(GenerationJob.plan_version_id)
        .join(GenerationReference, GenerationReference.version_id == GenerationJob.version_id)
        .where(GenerationReference.reference_id == ref.reference_id)
    )
    if session.scalar(
        select(PracticalSession.session_id)
        .where(
            PracticalSession.candidate_id == str(candidate),
            PracticalSession.plan_version_id.in_(plans),
            PracticalSession.created_at > datetime.now(UTC) - timedelta(days=1),
        )
        .limit(1)
    ):
        raise HTTPException(409, "Reference family repeat cooldown active")


def purge(session, subject):
    versions = select(GenerationReference.version_id).where(
        (GenerationReference.author_id == subject) | (GenerationReference.approved_by == subject)
    )
    session.execute(
        delete(GenerationPreview).where(
            (GenerationPreview.author_id == subject) | GenerationPreview.version_id.in_(versions)
        )
    )
    from reverse_hr.services.assessment.domain.assessment import ContentRevision
    from reverse_hr.services.assessment.domain.assessment_sessions import PlanVersion

    owned_jobs = list(
        session.scalars(
            select(GenerationJob).where(
                (GenerationJob.author_id == subject) | GenerationJob.version_id.in_(versions)
            )
        )
    )
    for job in owned_jobs:
        plan = session.get(PlanVersion, job.plan_version_id) if job.plan_version_id else None
        content = session.get(ContentRevision, job.revision_id) if job.revision_id else None
        if plan:
            plan.status, plan.version = "retired", plan.version + 1
        if content:
            content.status, content.version = "retired", content.version + 1
    # Do not leave any provider output or original authored text in the owner's service.
    session.execute(
        delete(GenerationJob).where(
            (GenerationJob.author_id == subject) | GenerationJob.version_id.in_(versions)
        )
    )
    session.execute(delete(GenerationReference).where(GenerationReference.version_id.in_(versions)))
