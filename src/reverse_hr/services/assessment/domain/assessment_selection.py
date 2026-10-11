"""Reviewed parameter variants and server-side rotation of immutable pinned plans."""

import copy
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, select, update
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.core import Contract
from reverse_hr.services.assessment.domain.assessment import (
    AssessmentBase,
    ContentFamily,
    ContentPackage,
    ContentRevision,
    RevisionView,
    event,
    revision,
    revision_view,
)
from reverse_hr.services.assessment.domain.assessment_sessions import (
    AssessmentSubject,
    PlanVersion,
    PracticalSession,
    ReasonCommand,
    SessionCommand,
    SessionView,
    admit_session,
    emit,
    guard_session_admission,
    session_view,
    subject_lock,
    utc,
)
from reverse_hr.shared.auth import Actor
from reverse_hr.shared.commands import CommandKey, ExpectedVersion, execute


class SelectionPolicy(AssessmentBase):
    __tablename__ = "assessment_selection_policies"
    policy_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_reason: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class VariantTemplate(AssessmentBase):
    __tablename__ = "assessment_variant_templates"
    template_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    data: Mapped[dict] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16))
    version: Mapped[int]
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36))
    review_reason: Mapped[str | None] = mapped_column(String(2000))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class GeneratedVariant(AssessmentBase):
    __tablename__ = "assessment_generated_variants"
    __table_args__ = (UniqueConstraint("template_id", "parameter_digest"),)
    revision_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    template_id: Mapped[str] = mapped_column(String(36))
    parameters: Mapped[dict] = mapped_column(JSON)
    parameter_digest: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[str] = mapped_column(String(36), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class PolicyCommand(Contract):
    name: str = Field(min_length=1, max_length=200, pattern=r"\S")
    plan_version_ids: list[UUID] = Field(min_length=2, max_length=100)
    grade_policy_ids: dict[UUID, UUID] = Field(default_factory=dict, max_length=100)
    family_cooldown_seconds: int = Field(default=86400, strict=True, ge=0, le=31536000)
    variant_cooldown_seconds: int = Field(default=2592000, strict=True, ge=0, le=31536000)
    window_seconds: int = Field(default=2592000, strict=True, ge=60, le=31536000)
    family_candidate_limit: int = Field(default=2, strict=True, ge=1, le=1000)
    family_global_limit: int = Field(default=1000, strict=True, ge=1, le=1000000)
    candidate_session_limit: int = Field(default=10, strict=True, ge=1, le=1000)

    @model_validator(mode="after")
    def unique(self):
        if len(set(self.plan_version_ids)) != len(self.plan_version_ids):
            raise ValueError("Duplicate plan")
        if self.grade_policy_ids and set(self.grade_policy_ids) != set(self.plan_version_ids):
            raise ValueError("Graded rotation requires a policy for every alternative")
        return self


class TemplateCommand(Contract):
    base_revision_id: UUID
    allowed_parameters: dict[str, list[str]] = Field(min_length=1, max_length=12)

    @model_validator(mode="after")
    def bounded(self):
        for key, values in self.allowed_parameters.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", key):
                raise ValueError("Invalid parameter name")
            if not 1 <= len(values) <= 20 or len(set(values)) != len(values):
                raise ValueError("Parameter values must be bounded and unique")
            if any(not value.strip() or len(value) > 200 or "{{" in value for value in values):
                raise ValueError("Invalid parameter value")
        return self


class GenerateCommand(Contract):
    parameters: dict[str, str] = Field(min_length=1, max_length=12)
    family_version: int = Field(strict=True, ge=1)


class SelectedSessionCommand(Contract):
    selection_policy_id: UUID
    assessment_consent_id: UUID
    grade_policy_id: UUID | None = None


class ReviewView(Contract):
    id: UUID
    status: str
    version: int
    data: dict


class HistoryItem(Contract):
    session_id: UUID
    plan_version_id: UUID
    family_ids: list[UUID]
    revision_ids: list[UUID]
    issued_at: datetime
    status: str


class SelectionOffer(Contract):
    policy_id: UUID
    name: str
    specialization: str
    grade: str
    demo: bool = True


router = APIRouter(prefix="/v1", tags=["assessment-selection"])


def selection_digest(data):
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def reviewed_view(row):
    return ReviewView(
        id=row.policy_id if isinstance(row, SelectionPolicy) else row.template_id,
        status=row.status,
        version=row.version,
        data=row.data,
    ).model_dump(mode="json")


@router.get("/assessment-selection-policies", response_model=list[SelectionOffer])
def selection_offers(request: Request, actor: Actor):
    actor.require("candidate")
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        result = []
        for row in session.scalars(
            select(SelectionPolicy)
            .where(SelectionPolicy.status == "published")
            .order_by(SelectionPolicy.policy_id)
        ):
            try:
                for owner in {row.created_by, row.reviewed_by} - {None}:
                    restriction = session.get(AssessmentSubject, owner)
                    if restriction and restriction.blocked:
                        raise HTTPException(409)
                    request.app.state.processing_access.check(UUID(owner))
            except HTTPException as exc:
                if exc.status_code == 409:
                    continue
                raise
            policy = PolicyCommand(**row.data)
            plan = session.get(PlanVersion, str(policy.plan_version_ids[0]))
            if plan is not None:
                result.append(
                    SelectionOffer(
                        policy_id=row.policy_id,
                        name=policy.name,
                        specialization=plan.specialization,
                        grade=plan.grade,
                    )
                )
        return result


def configuration(request, actor, model, key):
    actor.require("content_admin", mfa=True)
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        row = session.get(model, str(key))
        if row is None:
            raise HTTPException(404)
        return reviewed_view(row)


@router.get("/assessment-selection-policies/{policy_id}", response_model=ReviewView)
def get_selection_policy(request: Request, actor: Actor, policy_id: UUID):
    return configuration(request, actor, SelectionPolicy, policy_id)


@router.get("/assessment-variant-templates/{template_id}", response_model=ReviewView)
def get_variant_template(request: Request, actor: Actor, template_id: UUID):
    return configuration(request, actor, VariantTemplate, template_id)


def families(session, plan):
    result = set()
    for revision_id in plan.revision_ids:
        content = session.get(ContentRevision, revision_id)
        if content is None:
            raise HTTPException(409, "Missing family provenance")
        result.add(content.family_id)
    return result


def comparable(session, body):
    plans = [session.get(PlanVersion, str(key)) for key in body.plan_version_ids]
    if any(plan is None or plan.status != "published" for plan in plans):
        raise HTTPException(409, "Every alternative must be published")
    signatures = []
    for plan in plans:
        if body.grade_policy_ids:
            from reverse_hr.services.assessment.domain.assessment_grades import policy_for

            policy_for(session, body.grade_policy_ids[UUID(plan.plan_version_id)], plan)
        components = []
        for stage in plan.stages:
            content = session.get(ContentRevision, stage["revision_id"])
            if content is None or content.status != "published":
                raise HTTPException(409)
            task = next(t for t in content.content["tasks"] if t["key"] == stage["task_key"])
            components.append(
                (
                    stage["format"],
                    stage["duration_seconds"],
                    bool(task.get("follows_task_key")),
                    tuple(
                        sorted(
                            (r["competency"], r["points"], r["evidence"]) for r in task["rubric"]
                        )
                    ),
                )
            )
        signatures.append((plan.specialization, plan.grade, tuple(components)))
    if any(signature != signatures[0] for signature in signatures):
        raise HTTPException(409, "Alternatives must cover the same assessment structure")
    return plans


@router.post("/assessment-selection-policies", response_model=ReviewView, status_code=201)
def create_policy(request: Request, actor: Actor, body: PolicyCommand, idempotency: CommandKey):
    actor.require("content_admin", mfa=True)

    def change(session):
        comparable(session, body)
        row = SelectionPolicy(
            policy_id=str(uuid4()),
            data=body.model_dump(mode="json"),
            status="draft",
            version=1,
            created_by=str(actor.subject),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        emit(session, request, row.policy_id, 1, "selection_policy_created", {})
        return reviewed_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_selection_policy",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
    )


def transition(request, actor, model, key, body, idempotency, expected, status):
    actor.require("content_admin", mfa=True)
    column = model.policy_id if model is SelectionPolicy else model.template_id

    def change(session):
        row = session.scalar(select(model).where(column == str(key)).with_for_update())
        if row is None:
            raise HTTPException(404)
        if row.version != expected or row.status != (
            "draft" if status == "published" else "published"
        ):
            raise HTTPException(409)
        if status == "published":
            if row.created_by == str(actor.subject):
                raise HTTPException(403, "An independent content reviewer is required")
            request.app.state.processing_access.check(UUID(row.created_by))
            if model is SelectionPolicy:
                comparable(session, PolicyCommand(**row.data))
            else:
                template_base(session, TemplateCommand(**row.data))
        row.status, row.version = status, expected + 1
        row.reviewed_by, row.review_reason = str(actor.subject), body.reason
        emit(session, request, str(key), row.version, "selection_configuration_" + status, {})
        return reviewed_view(row)

    def guard(session):
        # Consistent subject order also covers reviewer / author privacy restrictions.
        row = session.get(model, str(key))
        owners = {str(actor.subject)} | ({row.created_by} if row else set())
        for owner in sorted(owners):
            subject_lock(
                session, owner, allow_blocked=status == "retired" and owner != str(actor.subject)
            )

    return execute(
        request.app.state.engine,
        actor.subject,
        f"{model.__tablename__}:{key}:{status}",
        idempotency,
        {"reason": body.reason, "version": expected},
        change,
        guard=guard,
    )


@router.post("/assessment-selection-policies/{policy_id}/publish", response_model=ReviewView)
def publish_policy(
    request: Request,
    actor: Actor,
    policy_id: UUID,
    body: ReasonCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return transition(
        request,
        actor,
        SelectionPolicy,
        policy_id,
        body,
        idempotency,
        int(if_match.strip('"')),
        "published",
    )


@router.post("/assessment-selection-policies/{policy_id}/retire", response_model=ReviewView)
def retire_policy(
    request: Request,
    actor: Actor,
    policy_id: UUID,
    body: ReasonCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return transition(
        request,
        actor,
        SelectionPolicy,
        policy_id,
        body,
        idempotency,
        int(if_match.strip('"')),
        "retired",
    )


def template_base(session, body):
    base = session.get(ContentRevision, str(body.base_revision_id))
    if base is None or base.status != "published":
        raise HTTPException(409, "Template base must be published")
    tokens = set()
    for task in base.content["tasks"]:
        for field in ("instruction", "reference_answer"):
            tokens.update(re.findall(r"\{\{([a-z][a-z0-9_]{0,31})\}\}", task[field]))
    if tokens != set(body.allowed_parameters):
        raise HTTPException(422, "Parameter declarations must exactly match text placeholders")
    return base


@router.post("/assessment-variant-templates", response_model=ReviewView, status_code=201)
def create_template(request: Request, actor: Actor, body: TemplateCommand, idempotency: CommandKey):
    actor.require("content_admin", mfa=True)

    def change(session):
        template_base(session, body)
        row = VariantTemplate(
            template_id=str(uuid4()),
            data=body.model_dump(mode="json"),
            status="draft",
            version=1,
            created_by=str(actor.subject),
            created_at=datetime.now(UTC),
        )
        session.add(row)
        emit(session, request, row.template_id, 1, "variant_template_created", {})
        return reviewed_view(row)

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_variant_template",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=lambda session: subject_lock(session, actor.subject),
    )


@router.post("/assessment-variant-templates/{template_id}/publish", response_model=ReviewView)
def publish_template(
    request: Request,
    actor: Actor,
    template_id: UUID,
    body: ReasonCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return transition(
        request,
        actor,
        VariantTemplate,
        template_id,
        body,
        idempotency,
        int(if_match.strip('"')),
        "published",
    )


@router.post("/assessment-variant-templates/{template_id}/retire", response_model=ReviewView)
def retire_template(
    request: Request,
    actor: Actor,
    template_id: UUID,
    body: ReasonCommand,
    idempotency: CommandKey,
    if_match: ExpectedVersion,
):
    return transition(
        request,
        actor,
        VariantTemplate,
        template_id,
        body,
        idempotency,
        int(if_match.strip('"')),
        "retired",
    )


@router.post(
    "/assessment-variant-templates/{template_id}/generate",
    response_model=RevisionView,
    status_code=201,
)
def generate(
    request: Request,
    actor: Actor,
    template_id: UUID,
    body: GenerateCommand,
    idempotency: CommandKey,
):
    actor.require("content_admin", mfa=True)

    def change(session):
        template = session.scalar(
            select(VariantTemplate)
            .where(VariantTemplate.template_id == str(template_id))
            .with_for_update()
        )
        if template is None:
            raise HTTPException(404)
        if template.status != "published":
            raise HTTPException(409)
        specification = TemplateCommand(**template.data)
        base = template_base(session, specification)
        if set(body.parameters) != set(specification.allowed_parameters) or any(
            value not in specification.allowed_parameters[key]
            for key, value in body.parameters.items()
        ):
            raise HTTPException(422, "Parameters are outside the reviewed bounds")
        content = copy.deepcopy(base.content)
        for task in content["tasks"]:
            for field in ("instruction", "reference_answer"):
                task[field] = re.sub(
                    r"\{\{([a-z][a-z0-9_]{0,31})\}\}",
                    lambda match: body.parameters[match[1]],
                    task[field],
                )
        package = ContentPackage(**content)
        parameter_digest = hashlib.sha256(
            json.dumps(body.parameters, sort_keys=True).encode()
        ).hexdigest()
        if session.scalar(
            select(GeneratedVariant).where(
                GeneratedVariant.template_id == str(template_id),
                GeneratedVariant.parameter_digest == parameter_digest,
            )
        ):
            raise HTTPException(409, "This parameter combination already has a variant")
        result = session.execute(
            update(ContentFamily)
            .where(
                ContentFamily.family_id == base.family_id,
                ContentFamily.version == body.family_version,
            )
            .values(version=body.family_version + 1)
        )
        if result.rowcount != 1:
            raise HTTPException(409, "Stale family version")
        row = revision(session, base.family_id, body.family_version + 1, package, actor)
        session.add(
            GeneratedVariant(
                revision_id=row.revision_id,
                template_id=str(template_id),
                parameters=body.parameters,
                parameter_digest=parameter_digest,
                created_by=str(actor.subject),
                created_at=datetime.now(UTC),
            )
        )
        session.add(row)
        event(session, request, row, "created")
        return revision_view(row)

    def guard(session):
        row = session.get(VariantTemplate, str(template_id))
        owners = {str(actor.subject)} | (
            {owner for owner in (row.created_by, row.reviewed_by) if owner} if row else set()
        )
        for owner in sorted(owners):
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))

    return execute(
        request.app.state.engine,
        actor.subject,
        f"generate_variant:{template_id}",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
    )


def locked_policies(session):
    return list(
        session.scalars(
            select(SelectionPolicy)
            .where(SelectionPolicy.status == "published")
            .order_by(SelectionPolicy.policy_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
    )


def exposure(session, row):
    revisions = {stage["revision_id"] for stage in row.stages}
    family_ids = set()
    for key in revisions:
        revision = session.get(ContentRevision, key)
        if revision is None:
            raise HTTPException(409, "Incomplete exposure history")
        family_ids.add(revision.family_id)
    return family_ids, revisions, utc(row.created_at)


def eligible(session, candidate, plan, policy, now):
    scope = set()
    for key in policy.plan_version_ids:
        alternative = session.get(PlanVersion, str(key))
        if alternative is None:
            raise HTTPException(409, "Missing selection alternative")
        scope.update(families(session, alternative))
    selected_families = families(session, plan)
    if not selected_families & scope:
        return True
    selected_families &= scope
    revisions = set(plan.revision_ids)
    family_counts = dict.fromkeys(selected_families, 0)
    global_counts = dict.fromkeys(selected_families, 0)
    attempts = 0
    cutoff = now - timedelta(seconds=policy.window_seconds)
    # Cancellation counts as exposure: it must not enable rerolling already disclosed tasks.
    history_cutoff = now - timedelta(
        seconds=max(
            policy.window_seconds, policy.family_cooldown_seconds, policy.variant_cooldown_seconds
        )
    )
    for row in session.scalars(
        select(PracticalSession).where(PracticalSession.created_at >= history_cutoff)
    ):
        issued = utc(row.created_at)
        if issued < now - timedelta(
            seconds=max(
                policy.window_seconds,
                policy.family_cooldown_seconds,
                policy.variant_cooldown_seconds,
            )
        ):
            continue
        historical_families, historical_revisions, issued = exposure(session, row)
        if issued > cutoff:
            for key in selected_families & historical_families:
                global_counts[key] += 1
        if row.candidate_id != str(candidate):
            continue
        if historical_families & scope and issued > cutoff:
            attempts += 1
        if selected_families & historical_families and issued > now - timedelta(
            seconds=policy.family_cooldown_seconds
        ):
            return False
        if revisions & historical_revisions and issued > now - timedelta(
            seconds=policy.variant_cooldown_seconds
        ):
            return False
        if issued > cutoff:
            for key in selected_families & historical_families:
                family_counts[key] += 1
    return (
        attempts < policy.candidate_session_limit
        and all(count < policy.family_candidate_limit for count in family_counts.values())
        and all(count < policy.family_global_limit for count in global_counts.values())
    )


def enforce_limits(session, candidate, plan, grade_policy_id=None):
    now = datetime.now(UTC)
    for row in locked_policies(session):
        policy = PolicyCommand(**row.data)
        for owner in (row.created_by, row.reviewed_by):
            restriction = session.get(AssessmentSubject, owner) if owner else None
            if restriction is not None and restriction.blocked:
                scope = set().union(
                    *(
                        families(session, session.get(PlanVersion, str(key)))
                        for key in policy.plan_version_ids
                    )
                )
                if families(session, plan) & scope:
                    raise HTTPException(409, "Selection configuration owner is restricted")
        expected = policy.grade_policy_ids.get(UUID(plan.plan_version_id))
        if expected and expected != grade_policy_id:
            raise HTTPException(409, "The selected plan requires its pinned grade policy")
        if not eligible(session, candidate, plan, policy, now):
            raise HTTPException(409, "Assessment rotation or issuance limit reached")


@router.post("/assessment-selected-sessions", response_model=SessionView, status_code=201)
def selected_session(
    request: Request, actor: Actor, body: SelectedSessionCommand, idempotency: CommandKey
):
    actor.require("candidate")

    def change(session):
        policies = locked_policies(session)
        row = next(
            (row for row in policies if row.policy_id == str(body.selection_policy_id)), None
        )
        if row is None:
            raise HTTPException(409, "Selection policy is not active")
        policy = PolicyCommand(**row.data)
        now = datetime.now(UTC)
        history = [
            exposure(session, old)
            for old in session.scalars(
                select(PracticalSession).where(PracticalSession.candidate_id == str(actor.subject))
            )
        ]
        global_history = [
            exposure(session, old)
            for old in session.scalars(
                select(PracticalSession).where(
                    PracticalSession.created_at > now - timedelta(seconds=policy.window_seconds)
                )
            )
        ]

        def rank(plan):
            fs = families(session, plan)
            rs = set(plan.revision_ids)
            return (
                sum(bool(fs & old_fs) for old_fs, _, _ in history),
                sum(bool(rs & old_rs) for _, old_rs, _ in history),
                max(
                    (issued for old_fs, _, issued in history if fs & old_fs),
                    default=datetime.min.replace(tzinfo=UTC),
                ),
                sum(bool(fs & old_fs) for old_fs, _, _ in global_history),
                sum(bool(rs & old_rs) for _, old_rs, _ in global_history),
                plan.plan_version_id,
            )

        plans = [session.get(PlanVersion, str(key)) for key in policy.plan_version_ids]
        plans = sorted(
            (plan for plan in plans if plan is not None and plan.status == "published"), key=rank
        )
        for plan in plans:
            mapped_grade = policy.grade_policy_ids.get(UUID(plan.plan_version_id))
            if mapped_grade and body.grade_policy_id and body.grade_policy_id != mapped_grade:
                continue
            if not all(
                eligible(session, actor.subject, plan, PolicyCommand(**other.data), now)
                for other in policies
            ):
                continue
            command = SessionCommand(
                plan_version_id=plan.plan_version_id,
                assessment_consent_id=body.assessment_consent_id,
                grade_policy_id=policy.grade_policy_ids.get(UUID(plan.plan_version_id))
                or body.grade_policy_id,
            )
            # A retired suite/content/policy makes this alternative unavailable, never weakens pins.
            try:
                with session.begin_nested():
                    guard_session_admission(request, actor, command, session)
                    result = admit_session(request, actor, command, session)
                    created = session.get(PracticalSession, result["session_id"])
                    created.selection_policy_id = row.policy_id
                    created.selection_policy_snapshot = copy.deepcopy(row.data)
                    created.selection_policy_digest = selection_digest(row.data)
                    return session_view(created)
            except HTTPException as exc:
                if exc.status_code not in {404, 409}:
                    raise
        raise HTTPException(409, "No eligible reviewed alternative; limits were not relaxed")

    def present(session, result):
        row = session.get(PracticalSession, result["session_id"])
        if row is None or row.candidate_id != str(actor.subject):
            raise HTTPException(404)
        request.app.state.processing_access.check_assessment(actor.subject, UUID(row.consent_id))
        return session_view(row)

    def guard(session):
        # Lock every possible proof owner before picking an alternative. Nested admission then
        # acquires no new subject locks in a different order.
        from reverse_hr.contracts.session_test_pins import stored_pins
        from reverse_hr.services.assessment.domain.assessment_grades import (
            GradePolicy,
            calibration_owners,
        )
        from reverse_hr.services.assessment.domain.assessment_plan_tests import owner_ids

        row = session.get(SelectionPolicy, str(body.selection_policy_id))
        owners = {str(actor.subject)}
        if row is not None:
            owners.update(owner for owner in (row.created_by, row.reviewed_by) if owner)
            policy = PolicyCommand(**row.data)
            for key in policy.plan_version_ids:
                plan = session.get(PlanVersion, str(key))
                if plan is not None:
                    try:
                        owners.update(owner_ids(session, actor.subject, stored_pins(plan)))
                    except (HTTPException, ValueError):
                        # Unavailable evidence is rejected again when considering that plan.
                        pass
            policy_ids = set(policy.grade_policy_ids.values())
            if body.grade_policy_id:
                policy_ids.add(body.grade_policy_id)
            for key in policy_ids:
                grade = session.get(GradePolicy, str(key))
                if grade:
                    owners.update(calibration_owners(grade))
        for owner in sorted(owners):
            subject_lock(session, owner)
        if row is not None:
            for owner in {row.created_by, row.reviewed_by} - {None}:
                request.app.state.processing_access.check(UUID(owner))
        request.app.state.processing_access.check_assessment(
            actor.subject, body.assessment_consent_id
        )

    return execute(
        request.app.state.engine,
        actor.subject,
        "create_selected_assessment_session",
        idempotency,
        body.model_dump(mode="json"),
        change,
        201,
        guard=guard,
        present=present,
    )


@router.get("/assessment-task-history", response_model=list[HistoryItem])
def task_history(request: Request, actor: Actor, after: str | None = None, limit: int = 50):
    actor.require("candidate")
    if not 1 <= limit <= 100:
        raise HTTPException(422)
    with Session(request.app.state.engine) as session, session.begin():
        subject_lock(session, actor.subject)
        request.app.state.processing_access.check(actor.subject)
        query = select(PracticalSession).where(PracticalSession.candidate_id == str(actor.subject))
        if after is not None:
            try:
                cursor = session.get(PracticalSession, str(UUID(after)))
            except ValueError as exc:
                raise HTTPException(422) from exc
            if cursor is None or cursor.candidate_id != str(actor.subject):
                raise HTTPException(404)
            query = query.where(
                (PracticalSession.created_at < cursor.created_at)
                | (
                    (PracticalSession.created_at == cursor.created_at)
                    & (PracticalSession.session_id < cursor.session_id)
                )
            )
        result = []
        for row in session.scalars(
            query.order_by(
                PracticalSession.created_at.desc(), PracticalSession.session_id.desc()
            ).limit(limit)
        ):
            fs, rs, issued = exposure(session, row)
            result.append(
                HistoryItem(
                    session_id=row.session_id,
                    plan_version_id=row.plan_version_id,
                    family_ids=sorted(fs),
                    revision_ids=sorted(rs),
                    issued_at=issued,
                    status=row.status,
                )
            )
        return result
