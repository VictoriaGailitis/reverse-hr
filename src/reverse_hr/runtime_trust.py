"""Operator allowlist plus Runner attestation; no automatic scoring activation."""

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import UUID

from pydantic import Field

from reverse_hr.contracts import Contract
from reverse_hr.runner_readiness import ProbeRecord
from reverse_hr.runtime_policy import TrustedRuntime
from reverse_hr.test_suites import digest

RUNTIME_CONTEXT = b"reverse-hr.suite-runtime-attestation.v1\0"


class RuntimeAttestation(Contract):
    version: Literal[1] = 1
    producer: Literal["code-runner"] = "code-runner"
    purpose: Literal["suite-runtime-attestation"] = "suite-runtime-attestation"
    validation_id: UUID
    owner_id: UUID
    proof_digest: str = Field(pattern=r"^[a-f0-9]{64}$")
    probe: ProbeRecord
    issued_at: datetime


class RuntimeDecision(Contract):
    validation_id: UUID
    runtime_admitted: bool = Field(strict=True)
    reason: Literal[
        "admitted",
        "policy_missing",
        "policy_expired",
        "policy_not_yet_active",
        "attestation_missing",
        "attestation_expired",
        "verdict_rejected",
        "suite_inactive",
    ]
    policy_id: UUID | None = None
    demo: Literal[True] = True
    scoring_enabled: Literal[False] = False


def check_binding(proof, report, now=None):
    now = now or datetime.now(UTC)
    times = (proof.completed_at, report.issued_at, report.probe.checked_at)
    if any(value.tzinfo is None for value in times) or (
        report.validation_id != proof.validation_id
        or report.owner_id != proof.owner_id
        or report.proof_digest != digest(proof)
        or report.probe.fingerprint != proof.pin.runtime_fingerprint
        or not report.probe.checked_at <= proof.completed_at <= report.issued_at <= now
        or proof.completed_at - report.probe.checked_at > timedelta(hours=24)
    ):
        raise ValueError("Runtime attestation does not bind the verdict and prior probe")


def decide(proof, report, policies: list[TrustedRuntime], *, now=None, active=True):
    now = now or datetime.now(UTC)

    def result(reason, policy_id=None):
        return RuntimeDecision(
            validation_id=proof.validation_id,
            runtime_admitted=reason == "admitted",
            reason=reason,
            policy_id=policy_id,
        )

    if not active:
        return result("suite_inactive")
    if proof.verdict != "accepted":
        return result("verdict_rejected")
    if report is None:
        return result("attestation_missing")
    check_binding(proof, report, now)
    if report.probe.checked_at < now - timedelta(hours=24):
        return result("attestation_expired")
    matched = next(
        (
            p
            for p in policies
            if p.node_id == report.probe.node_id and p.fingerprint == report.probe.fingerprint
        ),
        None,
    )
    if matched is None:
        return result("policy_missing")
    if matched.approved_at > now or matched.approved_at > report.probe.checked_at:
        return result("policy_not_yet_active", matched.policy_id)
    if matched.expires_at <= now:
        return result("policy_expired", matched.policy_id)
    return result("admitted", matched.policy_id)
