"""Explicit uncalibrated demo freshness and advice, with separate retry/grade cooldowns."""

from datetime import UTC, datetime

from reverse_hr.contracts import Grade
from reverse_hr.qualification_contracts import QualificationAdvice


def freshness(assessed_at, now, policy=None):
    age = max(0, (now - assessed_at).days)
    current_days = policy.current_days if policy else 180
    expiry_days = policy.expiry_days if policy else 365
    return (
        ("current", 100)
        if age <= current_days
        else ("aging", 50)
        if age <= expiry_days
        else ("expired", 0)
    )


def advice(decision_id, summary, current_grade, now=None, policy=None):
    now = now or datetime.now(UTC)
    proof = summary.qualification
    state, _ = freshness(proof.assessed_at, now, policy=policy)
    feedback = []
    for key, score in sorted(proof.competency_scores.items(), key=lambda item: (item[1], item[0])):
        target = proof.competency_minimums.get(key, policy.advice_target if policy else 70)
        if score < target:
            basis = (
                "approved assessment minimum"
                if key in proof.competency_minimums
                else (
                    "approved matching advice target"
                    if policy and not policy.demo
                    else "uncalibrated demo advice target"
                )
            )
            feedback.append(
                f"{key}: {score}/100; practice and repeat a reviewed task for this competency "
                f"(target {target}, {basis})."
            )
    grades = list(Grade)
    next_grade = None
    if (
        summary.status == "confirmed"
        and proof.score >= (policy.next_grade_score if policy else 90)
        and all(
            value
            >= max(
                policy.next_grade_competency if policy else 80,
                proof.competency_minimums.get(key, 0),
            )
            for key, value in proof.competency_scores.items()
        )
        and state == "current"
        and current_grade == summary.target_grade
        and current_grade != grades[-1]
        and now >= proof.grade_change_available_at
        and now >= proof.next_attempt_at
    ):
        next_grade = grades[grades.index(current_grade) + 1]
    return QualificationAdvice(
        decision_id=decision_id,
        specialization=summary.specialization,
        assessed_at=proof.assessed_at,
        current_grade=current_grade,
        freshness=state,
        repeat_recommended=state != "current",
        retry_available=now >= proof.next_attempt_at,
        next_attempt_at=proof.next_attempt_at,
        grade_change_available_at=proof.grade_change_available_at,
        recommended_next_grade=next_grade,
        feedback=feedback,
        policy_version=policy.version if policy else "qualification-advice-demo-v1",
        calibrated=not policy.demo and not proof.demo if policy else False,
        demo=policy.demo or proof.demo if policy else True,
    )
