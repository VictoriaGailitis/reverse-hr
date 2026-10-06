"""Attest only a persisted, still-permitted verdict with a current local real probe."""

from datetime import UTC, datetime
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.orm import Session

from reverse_hr.domains.code_runner import subject_lock
from reverse_hr.processing_access import sign, verify
from reverse_hr.runner_readiness import fingerprint, read_record, require_execution_ready
from reverse_hr.runtime_trust import RUNTIME_CONTEXT, RuntimeAttestation, check_binding
from reverse_hr.test_suites import digest
from reverse_hr.validation_lifecycle import ValidationBatch
from reverse_hr.validation_verdict import (
    VERDICT_CONTEXT,
    SuiteVerdict,
    VerdictRecord,
    snapshot,
)


def attest(engine, owner_id, validation_id, access, admission, executor, signatures):
    owner, validation_id = UUID(str(owner_id)), UUID(str(validation_id))
    require_execution_ready(executor)
    probe = read_record(executor.settings.runner_verification_file)
    with Session(engine) as session, session.begin():
        subject_lock(session, owner)
        access.check(owner)
        plan, matrix = snapshot(session, owner, validation_id, executor)
    admission.check(owner, plan)
    require_execution_ready(executor)
    if read_record(executor.settings.runner_verification_file) != probe or (
        probe.node_id != executor.settings.runner_node_id
        or probe.fingerprint != fingerprint(executor)
        or probe.fingerprint != plan.pin.runtime_fingerprint
    ):
        raise HTTPException(409)
    with Session(engine) as session, session.begin():
        subject_lock(session, owner)
        access.check(owner)
        current_plan, current_matrix = snapshot(session, owner, validation_id, executor)
        if (plan, matrix) != (current_plan, current_matrix):
            raise HTTPException(409)
        row = session.get(VerdictRecord, str(validation_id))
        if row is None:
            raise HTTPException(409)
        try:
            proof = SuiteVerdict.model_validate(row.proof)
            verify(signatures, "code-runner", row.signature, VERDICT_CONTEXT, proof)
            if (
                row.owner_id != str(owner)
                or proof.owner_id != owner
                or proof.validation_id != validation_id
                or proof.pin != plan.pin
                or proof.plan_digest != digest(plan)
                or proof.captures_digest != digest(matrix)
                or proof.captures_count != len(matrix.captures)
                or session.get(ValidationBatch, str(validation_id)).status != proof.verdict
            ):
                raise ValueError("Corrupt verdict binding")
            report = RuntimeAttestation(
                validation_id=validation_id,
                owner_id=owner,
                proof_digest=digest(proof),
                probe=probe,
                issued_at=datetime.now(UTC),
            )
            check_binding(proof, report)
        except Exception as exc:
            raise HTTPException(409) from exc
        try:
            signed = sign(signatures, RUNTIME_CONTEXT, report)
            verify(signatures, "code-runner", signed, RUNTIME_CONTEXT, report)
        except Exception as exc:
            raise HTTPException(503) from exc
        return report, signed
