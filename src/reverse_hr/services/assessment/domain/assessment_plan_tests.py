"""Resolve reviewed runtime-admitted suites and recheck immutable private pins."""

from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select

from reverse_hr.contracts.runtime_trust import decide
from reverse_hr.contracts.session_test_pins import PlanSuitePin
from reverse_hr.contracts.test_suites import digest
from reverse_hr.services.assessment.domain.assessment import ContentRevision
from reverse_hr.services.assessment.domain.assessment_sessions import (
    AssessmentSubject,
    subject_lock,
)
from reverse_hr.services.assessment.domain.assessment_tests import TestSuite, view
from reverse_hr.services.assessment.domain.assessment_verdicts import (
    ValidationIntake,
    current_suite,
    verified_intake,
)


def owner_ids(session, actor_id, selections):
    owners = {str(actor_id)}
    for selection in selections:
        row = session.get(ValidationIntake, str(selection.validation_id))
        if row is None:
            raise HTTPException(409, "Validation proof unavailable")
        owners.add(row.owner_id)
    return owners


def guard_owners(request, session, actor_id, selections):
    owners = owner_ids(session, actor_id, selections)
    for owner in sorted(owners):
        subject_lock(session, owner)
        request.app.state.processing_access.check(UUID(owner))


def lock_suites(session, bindings):
    ids = {str(b.suite_id if hasattr(b, "suite_id") else b.pin.suite_id) for b in bindings}
    for suite_id in sorted(ids):
        if (
            session.scalar(
                select(TestSuite)
                .where(TestSuite.suite_id == suite_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            is None
        ):
            raise HTTPException(409)


def resolve(request, session, selections, stages, documents):
    if not selections:
        return []
    selected = {(str(s.revision_id), s.task_key): s for s in selections}
    eligible = {
        (str(revision), task["key"])
        for revision, document in documents.items()
        for task in document["tasks"]
        if task["format"] in {"code", "sql"}
        and any(c["evidence"] == "test_result" for c in task["rubric"])
    }
    if len(selected) != len(selections) or set(selected) != eligible:
        raise HTTPException(422, "Selections must cover exactly the code/SQL test_result stages")
    pins = []
    for position, stage in enumerate(stages):
        selection = selected.get((stage["revision_id"], stage["task_key"]))
        if selection is None:
            continue
        row = session.get(ValidationIntake, str(selection.validation_id))
        if row is None or row.suite_id != str(selection.suite_id):
            raise HTTPException(409)
        proof, report = verified_intake(request, row)
        suite = session.get(TestSuite, row.suite_id)
        if (
            suite is None
            or suite.revision_id != str(selection.revision_id)
            or suite.task_key != selection.task_key
        ):
            raise HTTPException(409)
        decision = decide(
            proof,
            report,
            request.app.state.settings.assessment_trusted_runtimes,
            active=current_suite(session, proof.owner_id, proof),
        )
        if not decision.runtime_admitted or report is None:
            raise HTTPException(409, "Runtime admission required")
        pins.append(
            PlanSuitePin(
                position=position,
                revision_id=selection.revision_id,
                task_key=selection.task_key,
                pin=proof.pin,
                validation_id=proof.validation_id,
                verdict_digest=digest(proof),
                attestation_digest=digest(report),
                node_id=report.probe.node_id,
                policy_id=decision.policy_id,
            )
        )
    return pins


def check_pins(request, session, pins, stages, *, current):
    if not pins:
        return
    lock_suites(session, pins)
    for revision_id in sorted({stage["revision_id"] for stage in stages}):
        if (
            session.scalar(
                select(ContentRevision)
                .where(ContentRevision.revision_id == revision_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            is None
        ):
            raise HTTPException(409)
    for binding in pins:
        if binding.position >= len(stages):
            raise HTTPException(409)
        stage = stages[binding.position]
        if (
            str(binding.revision_id) != stage["revision_id"]
            or binding.task_key != stage["task_key"]
            or stage["format"] not in {"code", "sql"}
            or (hasattr(binding, "stage_id") and str(binding.stage_id) != stage["stage_id"])
        ):
            raise HTTPException(409)
        row = session.get(ValidationIntake, str(binding.validation_id))
        if row is None or row.suite_id != str(binding.pin.suite_id):
            raise HTTPException(409, "Pinned validation proof unavailable")
        subject = session.get(AssessmentSubject, row.owner_id)
        if subject is not None and subject.blocked:
            raise HTTPException(409)
        proof, report = verified_intake(request, row)
        suite = session.scalar(
            select(TestSuite).where(TestSuite.suite_id == row.suite_id).with_for_update()
        )
        if (
            report is None
            or suite is None
            or proof.pin != binding.pin
            or suite.task_key != binding.task_key
            or suite.revision_id != str(binding.revision_id)
            or suite.definition_digest != binding.pin.definition_digest
            or suite.content_digest != binding.pin.content_digest
            or suite.created_by != str(proof.owner_id)
            or digest(proof) != binding.verdict_digest
            or digest(report) != binding.attestation_digest
            or report.probe.node_id != binding.node_id
            or proof.verdict != "accepted"
        ):
            raise HTTPException(409, "Corrupted pinned validation")
        # Even historical reads validate definition/content digests against the immutable catalogue.
        view(session, suite.suite_id)
        revision = session.get(ContentRevision, suite.revision_id)
        task = next(t for t in revision.content["tasks"] if t["key"] == binding.task_key)
        if any(task[k] != stage[k] for k in ("format", "instruction", "duration_seconds")):
            raise HTTPException(409, "Pinned stage differs from content")
        if current:
            decision = decide(
                proof,
                report,
                request.app.state.settings.assessment_trusted_runtimes,
                active=current_suite(session, proof.owner_id, proof),
            )
            if not decision.runtime_admitted or decision.policy_id != binding.policy_id:
                raise HTTPException(409, "Pinned runtime admission unavailable")
