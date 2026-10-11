"""Opt-in, own-node validation queue; retries never replay lost execution output."""

import argparse
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from fastapi import HTTPException
from sqlalchemy import JSON, DateTime, ForeignKey, String, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.contracts.runtime_trust import RUNTIME_CONTEXT, RuntimeAttestation, check_binding
from reverse_hr.contracts.suite_validation import ValidationPlan, build_plan
from reverse_hr.contracts.suite_verdict import VERDICT_CONTEXT, SuiteVerdict
from reverse_hr.contracts.test_suites import digest
from reverse_hr.platform.settings import Settings
from reverse_hr.protocols.processing_access import ProcessingAccess
from reverse_hr.protocols.suite_admission import SuiteAdmissionAccess
from reverse_hr.protocols.verdict_delivery import VerdictReceipt
from reverse_hr.services.code_runner.domain.code_runner import (
    RunnerBase,
    require_runner_mode,
    subject_lock,
)
from reverse_hr.services.code_runner.runner_readiness import fingerprint, require_execution_ready
from reverse_hr.services.code_runner.sandbox import (
    CleanupUnconfirmed,
    NsjailExecutor,
    SandboxUnavailable,
)
from reverse_hr.services.code_runner.validation_attestation import attest
from reverse_hr.services.code_runner.validation_lifecycle import (
    ValidationAttempt,
    ValidationBatch,
    execute_reserved,
    recover_one,
    reserve,
)
from reverse_hr.services.code_runner.validation_verdict import VerdictRecord, finalize
from reverse_hr.shared.db import enqueue as emit
from reverse_hr.shared.db import make_engine
from reverse_hr.shared.event_transport import Signatures
from reverse_hr.shared.signing import verify

MAX_FAILURES = 5


class ValidationWork(RunnerBase):
    __tablename__ = "validation_work"
    validation_id: Mapped[str] = mapped_column(
        ForeignKey("validation_batches.validation_id"),
        primary_key=True,
    )
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    node_id: Mapped[str] = mapped_column(String(36), index=True)
    scope_id: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16))
    failures: Mapped[int]
    next_run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(32))
    attestation: Mapped[dict | None] = mapped_column(JSON)
    attestation_signature: Mapped[str | None] = mapped_column(String(128))
    receipt: Mapped[dict | None] = mapped_column(JSON)


def guard_id(validation_id):
    return uuid5(NAMESPACE_URL, f"reverse-hr.validation-work:{validation_id}")


def enqueue_validation(engine, owner_id, plan, processing, admission, executor, *, retry=False):
    owner = UUID(str(owner_id))
    if executor.settings.service_name != "code-runner" or executor.settings.runner_node_id is None:
        raise SandboxUnavailable()
    plan = ValidationPlan.model_validate(plan.model_dump(mode="json"))
    require_execution_ready(executor)
    if fingerprint(executor) != plan.pin.runtime_fingerprint:
        raise SandboxUnavailable()
    # Fetch trusted expected outputs/definition and validate the entire supplied plan.
    definition = admission.fetch(owner, plan)
    if build_plan(definition, plan.pin, plan.validation_id) != plan:
        raise HTTPException(409)
    require_execution_ready(executor)
    if fingerprint(executor) != plan.pin.runtime_fingerprint:
        raise SandboxUnavailable()
    now, scope = datetime.now(UTC), executor.cleanup_scope()
    with Session(engine) as session, session.begin():
        subject_lock(session, owner)
        processing.check(owner)
        require_runner_mode(session, "execution")
        batch = session.get(ValidationBatch, str(plan.validation_id))
        if batch is None:
            batch = ValidationBatch(
                validation_id=str(plan.validation_id),
                owner_id=str(owner),
                plan=plan.model_dump(mode="json"),
                status="prepared",
                created_at=now,
            )
            session.add(batch)
            session.flush()
        elif (
            batch.owner_id != str(owner)
            or batch.plan != plan.model_dump(mode="json")
            or batch.status not in {"prepared", "captures_ready", "accepted", "rejected"}
        ):
            raise HTTPException(409)
        attempts = session.scalars(
            select(ValidationAttempt).where(ValidationAttempt.validation_id == batch.validation_id)
        ).all()
        if any(
            a.node_id != str(executor.settings.runner_node_id) or a.scope_id != scope
            for a in attempts
        ):
            raise HTTPException(409)
        row = session.get(ValidationWork, batch.validation_id)
        if row is not None:
            if (
                row.owner_id != str(owner)
                or row.node_id != str(executor.settings.runner_node_id)
                or row.scope_id != scope
            ):
                raise HTTPException(409)
            if retry:
                if row.status not in {"needs_attention", "stopped"}:
                    raise HTTPException(409)
                row.status, row.failures, row.error_code = "pending", 0, None
                row.next_run_at, row.updated_at = now, now
            return plan.validation_id
        session.add(
            ValidationWork(
                validation_id=batch.validation_id,
                owner_id=str(owner),
                node_id=str(executor.settings.runner_node_id),
                scope_id=scope,
                status="pending",
                failures=0,
                next_run_at=now,
                updated_at=now,
                error_code=None,
                attestation=None,
                attestation_signature=None,
                receipt=None,
            )
        )
    return plan.validation_id


def update_work(engine, validation_id, *, error=None, terminal=None):
    with Session(engine) as session, session.begin():
        row = session.get(ValidationWork, str(validation_id))
        if row is None:
            return
        subject_lock(session, row.owner_id, allow_blocked=True)
        session.refresh(row)
        if row.status != "pending":
            return
        now = datetime.now(UTC)
        row.updated_at, row.error_code = now, error
        if terminal:
            row.status = terminal
        elif error:
            row.failures += 1
            if row.failures >= MAX_FAILURES:
                row.status = "needs_attention"
            else:
                row.next_run_at = now + timedelta(seconds=min(300, 5 * 2 ** (row.failures - 1)))
        else:
            row.failures, row.next_run_at = 0, now


def orphan_cleanup(engine, node, scope, executor):
    with Session(engine) as session:
        batch_id = session.scalar(
            select(ValidationAttempt.validation_id)
            .where(
                ValidationAttempt.node_id == str(node),
                ValidationAttempt.scope_id == scope,
                ValidationAttempt.state != "cleaned",
                ~select(ValidationWork.validation_id)
                .where(
                    ValidationWork.validation_id == ValidationAttempt.validation_id,
                    ValidationWork.status == "pending",
                )
                .exists(),
            )
            .order_by(ValidationAttempt.created_at)
            .limit(1)
        )
    if batch_id is None:
        return False
    with executor.attempt_guard(guard_id(batch_id)):
        return recover_one(engine, node, executor, validation_id=batch_id)


def run_one(engine, processing, admission, delivery, executor, signatures):
    if executor.settings.service_name != "code-runner":
        raise SandboxUnavailable()
    node, scope = executor.settings.runner_node_id, executor.cleanup_scope()
    if node is None:
        raise SandboxUnavailable()
    # Cleanup does not depend on a fresh probe or remote service availability.
    if orphan_cleanup(engine, node, scope, executor):
        return True
    with Session(engine) as session:
        validation_id = session.scalar(
            select(ValidationWork.validation_id)
            .where(
                ValidationWork.node_id == str(node),
                ValidationWork.scope_id == scope,
                ValidationWork.status == "pending",
                ValidationWork.next_run_at <= datetime.now(UTC),
            )
            .order_by(ValidationWork.updated_at, ValidationWork.validation_id)
            .limit(1)
        )
    if validation_id is None:
        from reverse_hr.services.code_runner.generated_validation import dispatch_one

        return dispatch_one(engine, processing, admission, executor, signatures)
    # Stable OS fence for all stages, including remote delivery; no expiring lease is cleanup.
    with executor.attempt_guard(guard_id(validation_id)):
        try:
            if recover_one(engine, node, executor, validation_id=validation_id):
                update_work(
                    engine, validation_id, error="execution_interrupted", terminal="stopped"
                )
                return True
            require_execution_ready(executor)
            with Session(engine) as session, session.begin():
                row = session.get(ValidationWork, validation_id)
                if row is None or row.status != "pending":
                    return True
                if row.node_id != str(node) or row.scope_id != scope:
                    raise HTTPException(409)
                owner = UUID(row.owner_id)
                subject_lock(session, owner)
                processing.check(owner)
                batch = session.get(ValidationBatch, validation_id)
                if batch is None or batch.owner_id != str(owner):
                    raise HTTPException(409)
                state = batch.status
                report_data, report_signature = row.attestation, row.attestation_signature
            if state in {"inconclusive", "interrupted", "withdrawn"}:
                update_work(engine, validation_id, error="batch_inconclusive", terminal="stopped")
            elif state == "prepared":
                attempt = reserve(engine, owner, validation_id, processing, node, executor)
                if attempt is not None:
                    execute_reserved(engine, processing, admission, node, attempt, executor)
                update_work(engine, validation_id)
            elif state == "captures_ready":
                finalize(engine, owner, validation_id, processing, admission, executor, signatures)
                update_work(engine, validation_id)
            elif state in {"accepted", "rejected"}:
                if report_data is None:
                    report, signed = attest(
                        engine, owner, validation_id, processing, admission, executor, signatures
                    )
                    with Session(engine) as session, session.begin():
                        subject_lock(session, owner)
                        processing.check(owner)
                        row = session.get(ValidationWork, validation_id)
                        if row is None or row.status != "pending":
                            raise HTTPException(409)
                        row.attestation = report.model_dump(mode="json")
                        row.attestation_signature = signed
                    update_work(engine, validation_id)
                else:
                    deliver_one(
                        engine,
                        owner,
                        validation_id,
                        report_data,
                        report_signature,
                        processing,
                        admission,
                        delivery,
                        executor,
                        signatures,
                    )
            else:
                raise HTTPException(409)
        except CleanupUnconfirmed:
            # Preserve the obligation; the next own-batch tick performs cleanup only.
            update_work(engine, validation_id, error="cleanup_unconfirmed")
        except HTTPException as exc:
            update_work(
                engine,
                validation_id,
                error=(
                    "admission_closed"
                    if exc.status_code in {401, 403, 404, 409}
                    else "dependency_unavailable"
                ),
                terminal=("stopped" if exc.status_code in {401, 403, 404, 409} else None),
            )
        except SandboxUnavailable:
            update_work(engine, validation_id, error="runtime_unavailable")
        except Exception:
            # Store bounded codes only; exceptions can contain sources or credentials.
            update_work(engine, validation_id, error="dependency_unavailable")
    return True


def deliver_one(
    engine,
    owner,
    validation_id,
    data,
    signed,
    processing,
    admission,
    delivery,
    executor,
    signatures,
):
    proof, proof_signature = finalize(
        engine, owner, validation_id, processing, admission, executor, signatures
    )
    report = RuntimeAttestation.model_validate(data)
    verify(signatures, "code-runner", signed, RUNTIME_CONTEXT, report)
    check_binding(proof, report)
    if report.probe.node_id != executor.settings.runner_node_id:
        raise HTTPException(409)
    receipt = delivery.deliver(
        proof, proof_signature, attestation=report, attestation_signature=signed
    )
    receipt = VerdictReceipt.model_validate(receipt.model_dump(mode="json"))
    if (
        not receipt.allowed
        or receipt.candidate_id != owner
        or str(receipt.validation_id) != validation_id
        or receipt.proof_digest != digest(proof)
        or receipt.attestation_digest != digest(report)
        or receipt.verdict != proof.verdict
    ):
        raise HTTPException(503)
    with Session(engine) as session, session.begin():
        subject_lock(session, owner)
        processing.check(owner)
        row = session.get(ValidationWork, validation_id)
        record = session.get(VerdictRecord, validation_id)
        if (
            row is None
            or row.status != "pending"
            or row.attestation != data
            or row.attestation_signature != signed
            or record is None
            or record.proof != proof.model_dump(mode="json")
            or record.signature != proof_signature
        ):
            raise HTTPException(409)
        verify(
            signatures,
            "code-runner",
            record.signature,
            VERDICT_CONTEXT,
            SuiteVerdict.model_validate(record.proof),
        )
        row.status, row.failures, row.error_code = "done", 0, None
        row.receipt, row.updated_at = receipt.model_dump(mode="json"), datetime.now(UTC)
        emit(
            session,
            EventEnvelope(
                event_type="code-runner.validation_delivery_confirmed.v1",
                producer="code-runner",
                aggregate_id=UUID(validation_id),
                aggregate_version=3,
                correlation_id=UUID(validation_id),
                payload={"candidate_id": owner, "validation_id": UUID(validation_id)},
            ),
        )


def main():
    parser = argparse.ArgumentParser(description="Enqueue a signed, pinned validation plan")
    parser.add_argument("--owner-id", required=True, type=UUID)
    parser.add_argument("--plan-file", required=True, type=Path)
    parser.add_argument("--retry", action="store_true", help="Retry stopped dependency work safely")
    args = parser.parse_args()
    settings = Settings()
    if settings.service_name != "code-runner" or settings.runner_node_id is None:
        parser.error("Requires Code Runner and a stable node ID")
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        with args.plan_file.open("rb") as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        if len(raw) > 32 * 1024 * 1024:
            raise ValueError("Oversized plan")
        plan = ValidationPlan.model_validate_json(raw)
        processing, admission = ProcessingAccess(settings), SuiteAdmissionAccess(settings)
        processing._signatures = admission._signatures = Signatures.from_settings(settings)
        validation_id = enqueue_validation(
            engine,
            args.owner_id,
            plan,
            processing,
            admission,
            NsjailExecutor(settings),
            retry=args.retry,
        )
        print(f"validation_enqueued validation_id={validation_id}")
    except Exception:
        parser.exit(1, "validation_enqueue_unavailable\n")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
