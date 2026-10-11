"""Opt-in hidden-test worker with durable cleanup and immutable signed outcomes."""

from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from fastapi import HTTPException
from sqlalchemy import JSON, DateTime, String, UniqueConstraint, select
from sqlalchemy.orm import Mapped, Session, mapped_column

from reverse_hr.contracts.runner import Output
from reverse_hr.contracts.suite_validation import guest_input
from reverse_hr.contracts.test_suites import compare, digest
from reverse_hr.protocols.submitted_results import (
    DELIVERY,
    PROOF,
    RECEIPT,
    ResultReceipt,
    TestOutcome,
    TestProof,
    delivery_body,
)
from reverse_hr.services.code_runner.domain.code_runner import (
    RunnerBase,
    RunnerSubject,
    require_runner_mode,
    subject_lock,
)
from reverse_hr.services.code_runner.runner_monitor import StopMonitor
from reverse_hr.services.code_runner.runner_readiness import (
    fingerprint,
    read_record,
    require_execution_ready,
)
from reverse_hr.services.code_runner.sandbox import CleanupUnconfirmed, SandboxUnavailable
from reverse_hr.shared.db import consume_once
from reverse_hr.shared.signing import canonical, fresh, sign, verify

REFS = ("candidate_id", "session_id", "stage_id", "workspace_id", "snapshot_id")


class SubmittedJob(RunnerBase):
    __tablename__ = "submitted_jobs"
    stage_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    session_id: Mapped[str] = mapped_column(String(36))
    workspace_id: Mapped[str] = mapped_column(String(36))
    snapshot_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(24), default="pending")
    material: Mapped[dict | None] = mapped_column(JSON)
    probe: Mapped[dict | None] = mapped_column(JSON)
    failures: Mapped[int] = mapped_column(default=0)
    available_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    proof: Mapped[dict | None] = mapped_column(JSON)
    signature: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubmittedAttempt(RunnerBase):
    __tablename__ = "submitted_attempts"
    __table_args__ = (UniqueConstraint("stage_id", "ordinal"),)
    attempt_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    stage_id: Mapped[str] = mapped_column(String(36), index=True)
    candidate_id: Mapped[str] = mapped_column(String(36), index=True)
    ordinal: Mapped[int]
    node_id: Mapped[str] = mapped_column(String(36), index=True)
    scope_id: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(16))
    capture: Mapped[dict | None] = mapped_column(JSON)
    outcome: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


def process_submission(session, event, processing=None):
    if (
        event.producer != "assessment"
        or event.event_type != "assessment.stage_submitted.v1"
        or set(event.payload) != set(REFS)
        or event.aggregate_id != event.payload["stage_id"]
        or event.aggregate_version != 3
        or event.occurred_at.tzinfo is None
        or event.occurred_at > datetime.now(UTC) + timedelta(minutes=2)
    ):
        raise HTTPException(409)

    def apply(session, event):
        subject = subject_lock(session, event.payload["candidate_id"], allow_blocked=True)
        if subject.blocked:
            return
        if processing is not None:
            try:
                processing.check(event.payload["candidate_id"])
            except HTTPException as exc:
                if exc.status_code == 409:
                    return
                raise
        refs = {k: str(event.payload[k]) for k in REFS}
        row = session.get(SubmittedJob, refs["stage_id"])
        if row:
            if any(getattr(row, k) != refs[k] for k in REFS):
                raise HTTPException(409)
        else:
            session.add(SubmittedJob(**refs, created_at=datetime.now(UTC)))

    return consume_once(session, "code-runner.submitted-tests", event, apply)


def recover_one(engine, executor):
    node, scope = str(executor.settings.runner_node_id), executor.cleanup_scope()
    with Session(engine) as session:
        row = session.scalar(
            select(SubmittedAttempt)
            .where(
                SubmittedAttempt.node_id == node,
                SubmittedAttempt.scope_id == scope,
                SubmittedAttempt.state != "cleaned",
            )
            .order_by(SubmittedAttempt.created_at)
            .limit(1)
        )
        if row is None:
            return False
        attempt_id, stage_id, candidate = row.attempt_id, row.stage_id, row.candidate_id
    with (
        executor.attempt_guard(uuid5(NAMESPACE_URL, f"submitted-stage:{stage_id}")),
        executor.attempt_guard(attempt_id),
    ):
        with Session(engine) as session:
            current = session.get(SubmittedAttempt, attempt_id)
            if current is None or current.state == "cleaned":
                return False
        executor.cleanup_attempt(attempt_id)
        with Session(engine) as session, session.begin():
            subject_lock(session, candidate, allow_blocked=True)
            row = session.get(SubmittedAttempt, attempt_id)
            if row is None:
                return True
            row.state, row.outcome, row.capture = "cleaned", None, None
            job = session.get(SubmittedJob, stage_id)
            if job:
                job.status = "interrupted"
            from reverse_hr.services.code_runner.domain.code_runner import finalize_runner_deletion

            subject = session.get(RunnerSubject, candidate)
            if subject.blocked:
                session.flush()
                finalize_runner_deletion(session, subject)
    return True


def live(engine, access, refs, expected):
    with Session(engine) as session:
        subject = session.get(RunnerSubject, str(refs["candidate_id"]))
        job = session.get(SubmittedJob, str(refs["stage_id"]))
        if subject is None or subject.blocked or job is None:
            return "access_withdrawn"
    current = access.fetch(**refs)
    if current != expected:
        return "access_withdrawn"
    return None


def _run_job(engine, access, executor, signatures, stage_id):
    # Cleanup does not need an execution probe; a broken runtime must still be cleaned.
    if recover_one(engine, executor):
        return True
    require_execution_ready(executor)
    node, scope = executor.settings.runner_node_id, executor.cleanup_scope()
    with Session(engine) as session:
        if session.scalar(
            select(SubmittedAttempt.attempt_id)
            .where(
                SubmittedAttempt.node_id == str(node),
                SubmittedAttempt.state != "cleaned",
                SubmittedAttempt.scope_id != scope,
            )
            .limit(1)
        ):
            raise SandboxUnavailable()
        job = session.get(SubmittedJob, stage_id)
        if job is None:
            return False
        refs = {k: UUID(getattr(job, k)) for k in REFS} | {
            "node_id": node,
            "runtime_fingerprint": fingerprint(executor),
        }
    with executor.attempt_guard(uuid5(NAMESPACE_URL, f"submitted-stage:{stage_id}")):
        material = access.fetch(**refs)
        source = access.source(material, **refs)
        require_execution_ready(executor)
        if fingerprint(executor) != material.binding.pin.runtime_fingerprint:
            raise SandboxUnavailable()
        with Session(engine) as session, session.begin():
            subject_lock(session, refs["candidate_id"])
            access.check(refs["candidate_id"])
            require_runner_mode(session, "execution")
            job = session.get(SubmittedJob, stage_id)
            if job is None or job.status not in {"pending", "ready", "delivery"}:
                return True
            if job.material is not None and job.material != material.model_dump(mode="json"):
                raise HTTPException(409)
            job.material = material.model_dump(mode="json")
            if job.probe is None:
                job.probe = read_record(executor.settings.runner_verification_file).model_dump(
                    mode="json"
                )
            attempts = list(
                session.scalars(
                    select(SubmittedAttempt)
                    .where(SubmittedAttempt.stage_id == stage_id)
                    .order_by(SubmittedAttempt.ordinal)
                )
            )
            if any(
                a.state != "cleaned"
                or a.outcome is None
                or a.ordinal != i
                or a.node_id != str(node)
                or a.scope_id != scope
                for i, a in enumerate(attempts)
            ):
                raise HTTPException(409)
            if len(attempts) > len(material.definition.cases):
                raise HTTPException(409)
            from reverse_hr.contracts.probe import ProbeRecord

            probe = ProbeRecord.model_validate(job.probe)
            if (
                probe.node_id != node
                or probe.fingerprint != material.binding.pin.runtime_fingerprint
                or probe.checked_at.tzinfo is None
                or datetime.now(UTC) - probe.checked_at > timedelta(hours=24)
            ):
                raise HTTPException(409)
            for i, a in enumerate(attempts):
                created = (
                    a.created_at.replace(tzinfo=UTC)
                    if a.created_at.tzinfo is None
                    else a.created_at
                )
                if created < probe.checked_at:
                    raise HTTPException(409)
                c = material.definition.cases[i]
                capture = Output.model_validate(a.capture)
                expected = TestOutcome(
                    case_key=c.key,
                    case_digest=digest(c),
                    criterion_key=c.criterion_key,
                    attempt_id=a.attempt_id,
                    input_digest=digest(guest_input(source, c)),
                    capture_digest=digest(capture),
                    verdict=compare(c, capture),
                )
                if expected.model_dump(mode="json") != a.outcome:
                    raise HTTPException(409)
            if job.status == "delivery":
                proof = TestProof.model_validate(job.proof)
                proof_signature = job.signature
                verify(signatures, "code-runner", proof_signature, PROOF, proof)
                if (
                    proof.binding != material.binding
                    or any(getattr(proof, k) != refs[k] for k in REFS)
                    or proof.snapshot_version != material.snapshot_version
                    or proof.snapshot_digest != material.snapshot_digest
                    or proof.probe.model_dump(mode="json") != job.probe
                    or [TestOutcome.model_validate(a.outcome) for a in attempts] != proof.outcomes
                ):
                    raise HTTPException(409)
                attempt_id = None
            elif len(attempts) == len(material.definition.cases):
                from reverse_hr.contracts.probe import ProbeRecord

                probe = ProbeRecord.model_validate(job.probe)
                proof = TestProof(
                    **{k: refs[k] for k in REFS},
                    snapshot_version=material.snapshot_version,
                    snapshot_digest=material.snapshot_digest,
                    binding=material.binding,
                    probe=probe,
                    completed_at=datetime.now(UTC),
                    outcomes=[TestOutcome.model_validate(a.outcome) for a in attempts],
                )
                job.proof, job.signature, job.status = (
                    proof.model_dump(mode="json"),
                    sign(signatures, PROOF, proof),
                    "delivery",
                )
                return True
            else:
                ordinal = len(attempts)
                case = material.definition.cases[ordinal]
                manifest = guest_input(source, case)
                attempt_id = uuid4()
                session.add(
                    SubmittedAttempt(
                        attempt_id=str(attempt_id),
                        stage_id=stage_id,
                        candidate_id=str(refs["candidate_id"]),
                        ordinal=ordinal,
                        node_id=str(node),
                        scope_id=scope,
                        state="reserved",
                        created_at=datetime.now(UTC),
                    )
                )
                job.status = "ready"
        if attempt_id is None:
            body = delivery_body(proof, proof_signature)
            raw, signature = access._send(
                "submitted-test-result",
                canonical(body),
                sign(signatures, DELIVERY, body),
                origin=access.settings.evaluation_api_url,
                max_bytes=4096,
            )
            receipt = ResultReceipt.model_validate_json(raw)
            verify(signatures, "evaluation", signature, RECEIPT, receipt)
            if (
                len(raw) > 4096
                or raw != canonical(receipt)
                or not fresh(receipt.issued_at)
                or receipt.candidate_id != proof.candidate_id
                or receipt.nonce != body.nonce
                or receipt.stage_id != proof.stage_id
                or receipt.proof_digest != digest(proof)
                or not receipt.allowed
            ):
                raise HTTPException(503)
            with Session(engine) as session, session.begin():
                subject_lock(session, refs["candidate_id"])
                access.check(refs["candidate_id"])
                job = session.get(SubmittedJob, stage_id)
                if job and job.proof == proof.model_dump(mode="json"):
                    job.status = "done"
            return True
        with executor.attempt_guard(attempt_id):
            if live(engine, access, refs, material) is not None:
                raise HTTPException(409)
            require_execution_ready(executor)
            with Session(engine) as session, session.begin():
                subject_lock(session, refs["candidate_id"])
                access.check(refs["candidate_id"])
                session.get(SubmittedAttempt, str(attempt_id)).state = "active"
            with StopMonitor(lambda: live(engine, access, refs, material)) as monitor:
                try:
                    raw_output = executor.execute(
                        material.definition.format,
                        manifest.model_dump(mode="json"),
                        attempt_id=attempt_id,
                        stop_check=monitor.current,
                    )
                    output = Output.model_validate(
                        {
                            k: getattr(raw_output, k)
                            for k in ("status", "stdout", "stderr", "exit_code", "reason")
                        }
                    )
                except CleanupUnconfirmed:
                    raise
                except Exception:
                    output = Output(status="technical_error", reason="sandbox_failed")
                executor.cleanup_attempt(attempt_id)
                require_execution_ready(executor)
                reason = monitor.current() or live(engine, access, refs, material)
                if reason:
                    output = (
                        Output(status="cancelled", reason="access_withdrawn")
                        if reason == "access_withdrawn"
                        else Output(status="technical_error", reason="admission_unavailable")
                    )
                outcome = TestOutcome(
                    case_key=case.key,
                    case_digest=digest(case),
                    criterion_key=case.criterion_key,
                    attempt_id=attempt_id,
                    input_digest=digest(manifest),
                    capture_digest=digest(output),
                    verdict=compare(case, output),
                )
                with Session(engine) as session, session.begin():
                    subject = subject_lock(session, refs["candidate_id"], allow_blocked=True)
                    attempt = session.get(SubmittedAttempt, str(attempt_id))
                    attempt.state = "cleaned"
                    if subject.blocked:
                        session.flush()
                        from reverse_hr.services.code_runner.domain.code_runner import (
                            finalize_runner_deletion,
                        )

                        finalize_runner_deletion(session, subject)
                    else:
                        access.check(refs["candidate_id"])
                        attempt.capture = output.model_dump(mode="json")
                        attempt.outcome = outcome.model_dump(mode="json")
                        session.get(SubmittedJob, stage_id).failures = 0
        return True


def run_one(engine, access, executor, signatures):
    now = datetime.now(UTC)
    with Session(engine) as session:
        stage_id = session.scalar(
            select(SubmittedJob.stage_id)
            .where(
                SubmittedJob.status.in_(["pending", "ready", "delivery"]),
                (SubmittedJob.available_at.is_(None) | (SubmittedJob.available_at <= now)),
            )
            .order_by(SubmittedJob.created_at)
            .limit(1)
        )
    if stage_id is None:
        return recover_one(engine, executor)
    try:
        return _run_job(engine, access, executor, signatures, stage_id)
    except CleanupUnconfirmed:
        raise
    except (HTTPException, SandboxUnavailable, ValueError) as exc:
        with Session(engine) as session, session.begin():
            row = session.get(SubmittedJob, stage_id)
            if row and row.status in {"pending", "ready", "delivery"}:
                subject_lock(session, row.candidate_id, allow_blocked=True)
                row.failures += 1
                row.available_at = now + timedelta(seconds=min(300, 5 * 2 ** min(row.failures, 5)))
                if isinstance(exc, ValueError) or (
                    isinstance(exc, HTTPException) and exc.status_code < 500
                ):
                    row.status = "blocked"
                elif row.failures >= 5:
                    row.status = "needs_attention"
        return True


def retry_job(engine, stage_id, access, executor):
    """Operator recovery of dependency failures; lost execution cannot be replayed."""
    require_execution_ready(executor)
    stage_id = str(UUID(str(stage_id)))
    with executor.attempt_guard(uuid5(NAMESPACE_URL, f"submitted-stage:{stage_id}")):
        with Session(engine) as session:
            job = session.get(SubmittedJob, stage_id)
            if job is None or job.status not in {"blocked", "needs_attention"}:
                raise HTTPException(409)
            refs = {k: UUID(getattr(job, k)) for k in REFS} | {
                "node_id": executor.settings.runner_node_id,
                "runtime_fingerprint": fingerprint(executor),
            }
        material = access.fetch(**refs)
        require_execution_ready(executor)
        with Session(engine) as session, session.begin():
            subject_lock(session, refs["candidate_id"])
            access.check(refs["candidate_id"])
            job = session.get(SubmittedJob, stage_id)
            if job is None or job.status not in {"blocked", "needs_attention"}:
                raise HTTPException(409)
            if job.material is not None and job.material != material.model_dump(mode="json"):
                raise HTTPException(409)
            attempts = list(
                session.scalars(
                    select(SubmittedAttempt).where(SubmittedAttempt.stage_id == stage_id)
                )
            )
            if any(
                a.state != "cleaned"
                or a.outcome is None
                or a.node_id != str(executor.settings.runner_node_id)
                or a.scope_id != executor.cleanup_scope()
                for a in attempts
            ):
                raise HTTPException(409)
            job.status = "delivery" if job.proof is not None else "ready"
            job.failures, job.available_at = 0, datetime.now(UTC)
