"""Leased generation, isolated suite verification and replenishment of original task pools."""

import copy
import hashlib
import json
import re
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.runtime_trust import decide
from reverse_hr.contracts.session_test_pins import PlanPins, TaskSuiteSelection
from reverse_hr.contracts.test_suites import digest
from reverse_hr.services.assessment.domain.assessment import (
    ContentFamily,
    ContentPackage,
    ContentRevision,
)
from reverse_hr.services.assessment.domain.assessment_generation import (
    GeneratedBundle,
    GenerationJob,
    GenerationReference,
    ReferenceCommand,
    new_job,
)
from reverse_hr.services.assessment.domain.assessment_sessions import (
    PlanVersion,
    PracticalSession,
    subject_lock,
    utc,
)
from reverse_hr.services.assessment.domain.assessment_tests import TestSuite
from reverse_hr.services.assessment.domain.assessment_verdicts import (
    ValidationIntake,
    current_suite,
    verified_intake,
)
from reverse_hr.services.assessment.generation_gateway import PROMPT
from reverse_hr.shared.db import enqueue


def wire_digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def validate_bundle(bundle, specification):
    reference = ReferenceCommand.model_validate(specification["reference"])
    task = bundle.task
    if (
        task.format != reference.format
        or task.duration_seconds != reference.duration_seconds
        or task.rubric != reference.rubric
        or task.follows_task_key is not None
    ):
        raise ValueError("Generated task changed pinned scoring or format")
    if re.search(r"https?://|www\.", task.instruction, re.I):
        raise ValueError("Generated task must be original and self-contained")
    if any(constraint not in task.instruction for constraint in reference.required_constraints):
        raise ValueError("Generated task omitted mandatory constraints")
    if task.format in {"code", "sql"}:
        suite = bundle.suite
        if (
            suite is None
            or suite.format != task.format
            or {c.criterion_key for c in suite.cases}
            != {c.key for c in task.rubric if c.evidence == "test_result"}
        ):
            raise ValueError("Missing or incompatible hidden tests")
        entry = "main.py" if task.format == "code" else "query.sql"
        if (
            next(f.content for f in suite.reference.files if f.path == entry)
            != task.reference_answer
        ):
            raise ValueError("Reference implementation changed")
        sources = [digest(suite.reference), *(digest(m.source) for m in suite.mutants)]
        if len(set(sources)) != len(sources):
            raise ValueError("Mutants must be distinct from reference and each other")
    elif bundle.suite is not None:
        raise ValueError("Non-executable formats cannot carry executable tests")
    return bundle


def similar(a, b):
    # A lexical near-duplicate check, not a claim of semantic equivalence.
    aa, bb = set(re.findall(r"\w+", a.casefold())), set(re.findall(r"\w+", b.casefold()))
    return bool(aa and bb and len(aa & bb) / len(aa | bb) > 0.9)


def check_owners(request, session, ref, author):
    for owner in sorted({ref.author_id, author, ref.approved_by} - {None}):
        subject_lock(session, owner)
        request.app.state.processing_access.check(UUID(owner))
    if ref.organization_id:
        request.app.state.market_access.require(
            "employer",
            "content-membership",
            candidate_id=UUID(author),
            actor_id=UUID(author),
            organization_id=UUID(ref.organization_id),
        )


def make_plan(request, session, job, reference, proof=None):
    from reverse_hr.services.assessment.domain.assessment_plan_tests import resolve

    ref = ReferenceCommand.model_validate(reference.data)
    task = GeneratedBundle.model_validate(job.output).task
    stage = dict(
        revision_id=job.revision_id,
        task_key=task.key,
        format=task.format,
        instruction=task.instruction,
        duration_seconds=task.duration_seconds,
    )
    selections = (
        [
            TaskSuiteSelection(
                revision_id=job.revision_id,
                task_key=task.key,
                suite_id=job.suite_id,
                validation_id=job.validation_id,
            )
        ]
        if proof
        else []
    )
    content = session.get(ContentRevision, job.revision_id)
    pins = resolve(request, session, selections, [stage], {job.revision_id: content.content})
    plan = PlanVersion(
        plan_version_id=str(uuid4()),
        name=ref.name,
        specialization=ref.specialization,
        grade=ref.grade.value,
        revision_ids=[job.revision_id],
        stages=[stage],
        test_pins=[pin.model_dump(mode="json") for pin in pins],
        test_pins_digest=digest(PlanPins(pins=pins)),
        duration_seconds=task.duration_seconds,
        status="published",
        version=1,
        created_by=job.author_id,
        created_at=datetime.now(UTC),
        review_reason="Validated original reference generation",
    )
    session.add(plan)
    session.flush()
    job.plan_version_id = plan.plan_version_id
    activate(request, session, job, reference)
    job.status, job.error = "ready", None


def activate(request, session, job, reference):
    if reference.status != "published":
        return
    ref = ReferenceCommand.model_validate(reference.data)
    plan = session.get(PlanVersion, job.plan_version_id)
    content = session.get(ContentRevision, job.revision_id)
    if (
        reference.grading_policy_id
        and reference.organization_id is None
        and not job.grade_policy_id
    ):
        from reverse_hr.services.assessment.domain.assessment_grades import (
            GradePolicy,
            Rules,
            plan_digest,
        )

        template = session.get(GradePolicy, reference.grading_policy_id)
        rules = Rules.model_validate(template.rules) if template else None
        if (
            template is None
            or template.status != "approved"
            or template.calibration is None
            or rules.generation_reference_id != UUID(reference.version_id)
            or set(rules.weights) != {c.key for c in ref.competencies}
        ):
            raise HTTPException(409, "Reference grading policy unavailable")
        for owner in {template.created_by, template.approved_by} - {None}:
            subject_lock(session, owner)
            request.app.state.processing_access.check(UUID(owner))
        policy = GradePolicy(
            policy_id=str(uuid4()),
            plan_version_id=plan.plan_version_id,
            plan_digest=plan_digest(plan),
            rules=copy.deepcopy(template.rules),
            rules_digest=template.rules_digest,
            status="approved",
            version=template.version,
            created_by=template.created_by,
            approved_by=template.approved_by,
            calibration=copy.deepcopy(template.calibration),
            calibration_digest=template.calibration_digest,
            approved_at=template.approved_at,
        )
        session.add(policy)
        job.grade_policy_id = policy.policy_id
    if reference.organization_id:
        from reverse_hr.services.assessment.domain.company_tasks import CompanyProposal

        if session.scalar(
            select(CompanyProposal.proposal_id).where(
                CompanyProposal.revision_id == content.revision_id
            )
        ):
            return
        session.add(
            CompanyProposal(
                proposal_id=str(uuid4()),
                organization_id=reference.organization_id,
                created_by=job.author_id,
                name=ref.name,
                content=content.content,
                digest=digest(ContentPackage.model_validate(content.content)),
                status="approved",
                version=1,
                created_at=datetime.now(UTC),
                reviewed_by=reference.approved_by,
                review_reason="Published company generation reference",
                reviewed_at=datetime.now(UTC),
                revision_id=content.revision_id,
            )
        )
    job.status, job.error = "ready", None


def replenish(request, session, now):
    for ref in session.scalars(
        select(GenerationReference)
        .where(GenerationReference.status == "published")
        .with_for_update()
    ):
        check_owners(request, session, ref, ref.author_id)
        jobs = list(
            session.scalars(select(GenerationJob).where(GenerationJob.version_id == ref.version_id))
        )
        current = sum(
            j.status in {"pending", "running", "validating"}
            or (
                j.status == "ready"
                and session.query(PracticalSession)
                .filter_by(plan_version_id=j.plan_version_id)
                .count()
                < ref.data["max_exposures"]
            )
            for j in jobs
        )
        if current >= ref.data["pool_size"]:
            continue
        # Bound spend even when a provider repeatedly produces invalid/duplicate tasks.
        recent = [j for j in jobs if utc(j.created_at) > now - timedelta(hours=1)]
        if len(recent) >= ref.data["pool_size"] * 3:
            continue
        prior = next((j for j in reversed(jobs) if j.status == "ready"), None)
        if prior is None:
            continue
        specification = copy.deepcopy(prior.specification)
        specification["variant_nonce"] = str(uuid4())
        job = new_job(
            request.app.state.settings,
            ref,
            ref.author_id,
            specification,
            wire_digest(specification),
        )
        session.add(job)
        return True
    return False


def run_one(request, gateway):
    engine, settings = request.app.state.engine, request.app.state.settings
    now = datetime.now(UTC)
    with Session(engine) as session, session.begin():
        # Process runtime verdicts before allocating more provider work.
        for job in session.scalars(
            select(GenerationJob)
            .where(GenerationJob.status == "validating")
            .order_by(GenerationJob.created_at)
            .with_for_update(skip_locked=True)
        ):
            reference = session.get(GenerationReference, job.version_id)
            check_owners(request, session, reference, job.author_id)
            if reference.status == "retired":
                job.status, job.error = "cancelled", "reference_retired"
                return True
            if not job.runtime_fingerprint:
                runtime = next(
                    (
                        r
                        for r in settings.assessment_trusted_runtimes
                        if r.approved_at <= now < r.expires_at
                    ),
                    None,
                )
                if runtime is None:
                    continue
                job.runtime_fingerprint, job.error = runtime.fingerprint, None
                enqueue(
                    session,
                    EventEnvelope(
                        event_type="assessment.generated_validation_requested.v1",
                        producer="assessment",
                        aggregate_id=UUID(job.generation_id),
                        aggregate_version=1,
                        correlation_id=UUID(job.generation_id),
                        payload={
                            "candidate_id": UUID(job.author_id),
                            "generation_id": UUID(job.generation_id),
                        },
                    ),
                )
                return True
            verdict = session.get(ValidationIntake, job.validation_id)
            if verdict is None:
                continue
            proof, report = verified_intake(request, verdict)
            decision = decide(
                proof,
                report,
                settings.assessment_trusted_runtimes,
                active=current_suite(session, UUID(job.author_id), proof),
            )
            if proof.verdict != "accepted":
                job.status, job.error = "rejected", "suite_validation_rejected"
                return True
            if not decision.runtime_admitted:
                job.error = "runtime_admission_pending"
                continue
            make_plan(request, session, job, reference, proof)
            return True
        job = session.scalar(
            select(GenerationJob)
            .where(
                GenerationJob.available_at <= now,
                (GenerationJob.status == "pending")
                | ((GenerationJob.status == "running") & (GenerationJob.lease_until < now)),
            )
            .order_by(GenerationJob.available_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if job is None:
            return replenish(request, session, now) if gateway is not None else False
        reference = session.get(GenerationReference, job.version_id)
        check_owners(request, session, reference, job.author_id)
        if reference.status == "retired":
            job.status, job.error = "cancelled", "reference_retired"
            return True
        if (
            gateway is None
            or gateway.model != job.model
            or gateway.configuration != job.configuration
            or hashlib.sha256(PROMPT.encode()).hexdigest() != job.prompt_digest
            or wire_digest(job.specification) != job.specification_digest
        ):
            job.status, job.error = "technical_failure", "provider_configuration_changed"
            return True
        from reverse_hr.shared.llm_configuration import GatewayConfiguration

        config = GatewayConfiguration.model_validate(job.configuration)
        max_attempts = min(3, config.stage_budget_microusd // (2 * config.reservation))
        if job.attempts >= max_attempts:
            job.status, job.error = "technical_failure", "attempt_budget_exhausted"
            return True
        job.attempts += 1
        token = str(uuid4())
        job.status, job.lease_token, job.lease_until = "running", token, now + timedelta(seconds=90)
        generation_id, specification = job.generation_id, copy.deepcopy(job.specification)
    bundle, error = None, None
    try:
        bundle = validate_bundle(
            GeneratedBundle.model_validate(gateway.generate(specification)), specification
        )
        if not gateway.validate(specification, bundle.model_dump(mode="json")):
            error, bundle = "semantic_validation_rejected", None
    except (ValueError, StopIteration):
        error = "invalid_generated_bundle"
    except Exception:
        error = "provider_unavailable"
    with Session(engine) as session, session.begin():
        job = session.scalar(
            select(GenerationJob)
            .where(GenerationJob.generation_id == generation_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if job is None or job.status != "running" or job.lease_token != token:
            return True
        if job.lease_until is None or utc(job.lease_until) <= datetime.now(UTC):
            job.status, job.error = "pending", "provider_lease_expired"
            job.available_at = datetime.now(UTC) + timedelta(seconds=30)
            job.lease_token, job.lease_until = None, None
            return True
        reference = session.get(GenerationReference, job.version_id)
        check_owners(request, session, reference, job.author_id)
        if reference.status == "retired":
            job.status, job.error = "cancelled", "reference_retired"
            return True
        if bundle is None:
            job.status = (
                "pending"
                if error == "provider_unavailable" and job.attempts < max_attempts
                else "technical_failure"
                if error == "provider_unavailable"
                else "rejected"
            )
            job.error, job.available_at = error, datetime.now(UTC) + timedelta(seconds=30)
            return True
        for prior in session.scalars(
            select(GenerationJob).where(
                GenerationJob.version_id == job.version_id,
                GenerationJob.output.is_not(None),
                GenerationJob.generation_id != job.generation_id,
            )
        ):
            if similar(bundle.task.instruction, prior.output["task"]["instruction"]):
                job.status, job.error = "rejected", "duplicate_task"
                return True
        job.output = bundle.model_dump(mode="json")
        job.output_digest = digest(bundle)
        ref = ReferenceCommand.model_validate(reference.data)
        family = session.scalar(
            select(ContentFamily)
            .where(ContentFamily.family_id == reference.reference_id)
            .with_for_update()
        )
        if family is None:
            family = ContentFamily(
                family_id=reference.reference_id,
                name=ref.name,
                specialization=ref.specialization,
                grade=ref.grade.value,
                version=0,
            )
            session.add(family)
            session.flush()
        family.version += 1
        package = ContentPackage(
            specialization=ref.specialization,
            grade=ref.grade,
            source_dataset="original-system",
            source_version=f"reference-{reference.number}",
            competencies=ref.competencies,
            tasks=[bundle.task],
        )
        content = ContentRevision(
            revision_id=str(uuid4()),
            family_id=family.family_id,
            number=family.version,
            content=package.model_dump(mode="json"),
            status="published",
            version=1,
            created_by=job.author_id,
            created_at=datetime.now(UTC),
            reviewed_by=reference.approved_by,
            review_reason=(
                "Original generation: reference policy approval; not an individual human review"
            ),
            published_at=datetime.now(UTC),
        )
        session.add(content)
        session.flush()
        job.revision_id = content.revision_id
        if bundle.suite:
            suite = TestSuite(
                suite_id=str(uuid4()),
                revision_id=content.revision_id,
                task_key=bundle.task.key,
                number=1,
                definition=bundle.suite.model_dump(mode="json"),
                definition_digest=digest(bundle.suite),
                content_digest=digest(package),
                status="reviewed",
                version=1,
                created_by=job.author_id,
                created_at=datetime.now(UTC),
                reviewed_by=reference.approved_by,
                review_reason="Reference policy approval; native validation required",
            )
            session.add(suite)
            job.suite_id, job.validation_id = suite.suite_id, str(uuid4())
            runtime = next(
                (
                    r
                    for r in settings.assessment_trusted_runtimes
                    if r.approved_at <= datetime.now(UTC) < r.expires_at
                ),
                None,
            )
            if runtime is None:
                job.status, job.error = "validating", "runtime_policy_missing"
                return True
            job.runtime_fingerprint, job.status = runtime.fingerprint, "validating"
            enqueue(
                session,
                EventEnvelope(
                    event_type="assessment.generated_validation_requested.v1",
                    producer="assessment",
                    aggregate_id=UUID(generation_id),
                    aggregate_version=1,
                    correlation_id=UUID(generation_id),
                    payload={
                        "candidate_id": UUID(job.author_id),
                        "generation_id": UUID(generation_id),
                    },
                ),
            )
        else:
            make_plan(request, session, job, reference)
    return True
