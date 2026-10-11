"""Exact item-analysis mathematics, role guards and signed live score provenance."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.services.assessment.domain.assessment_grades import GradeDecision
from reverse_hr.services.assessment.domain.assessment_sessions import PracticalSession
from reverse_hr.services.assessment.domain.task_analytics import (
    Bands,
    Observation,
    Scale,
    Simulation,
    quality,
    summarize,
)
from tests.services.assessment.test_assessment_grades import decide, proposal, review
from tests.services.assessment.test_assessment_grades import setup as setup
from tests.shared.test_event_transport import signatures as signatures


def item(i, score, grade="junior", rest=None):
    return Observation(
        profile_key=str(i),
        target_grade=grade,
        independent_grade=grade,
        score=score,
        rest_score=rest,
    )


def test_quality_boundaries_and_grade_specific_scale():
    bands = Bands(normal_from=50, good_from=80)
    assert [quality(value, bands) for value in (0, 49, 50, 79, 80, 100)] == [
        "poor",
        "poor",
        "normal",
        "normal",
        "good",
        "good",
    ]
    with pytest.raises(ValidationError):
        Bands(normal_from=80, good_from=80)
    scale = Scale()
    scale.by_grade["senior"] = Bands(normal_from=70, good_from=90)
    result = summarize([item(1, 60), item(2, 60, "senior")], scale, "synthetic")
    assert result.target_distributions[0].buckets[1].count == 1
    assert result.target_distributions[2].buckets[0].count == 1


def test_discrimination_uses_common_upper_threshold_and_independent_labels():
    data = [item(i, 80 if i < 3 else 0, "junior") for i in range(10)]
    data += [item(i + 10, 80 if i < 8 else 0, "middle") for i in range(10)]
    result = summarize(data, Scale(), "synthetic")
    assert result.contrasts[0].good_difference == 0.5
    assert result.contrasts[0].normal_or_better_difference == 0.5
    assert result.contrasts[1].status == "insufficient_data"
    scale = Scale()
    scale.by_grade["junior"] = Bands(normal_from=1, good_from=2)
    assert summarize(data, scale, "synthetic").contrasts[0].good_difference == 0.5
    data = [row.model_copy(update={"independent_grade": None}) for row in data]
    result = summarize(data, Scale(), "synthetic")
    assert result.sample_count == 20 and result.independent_label_count == 0
    assert result.contrasts[0].good_difference is None


def test_corrected_correlation_empty_constant_and_negative():
    assert summarize([], Scale(), "synthetic").correlation_status == "insufficient_data"
    data = [item(i, i * 10, rest=i * 10) for i in range(10)]
    assert summarize(data, Scale(), "synthetic").corrected_item_total_correlation == 1
    data = [item(i, i * 10, rest=100 - i * 10) for i in range(10)]
    assert summarize(data, Scale(), "synthetic").corrected_item_total_correlation == -1
    data = [item(i, 80, rest=i * 10) for i in range(10)]
    assert summarize(data, Scale(), "synthetic").correlation_status == "constant_scores"
    with pytest.raises(ValidationError):
        Simulation(observations=[item(1, 40), item(1, 70)], reason="Duplicate profiles")


def test_simulation_requires_privileged_mfa_and_never_stores_results(service, token):
    target = service("assessment")
    path = "/v1/task-analytics/simulate"
    body = dict(observations=[item(1, 80).model_dump(mode="json")], reason="Synthetic fixture")
    for roles, amr in [(("candidate",), ["mfa"]), (("content_admin",), [])]:
        assert (
            target.client.post(path, json=body, headers=token(uuid4(), roles, amr=amr)).status_code
            == 403
        )
    response = target.client.post(
        path, json=body, headers=token(uuid4(), ("content_admin",), amr=["mfa"])
    )
    assert response.status_code == 200, response.text
    assert response.json()["source"] == "synthetic"
    assert "profile_key" not in response.text


def test_live_completed_evidence_avoids_circular_grade_and_honors_privacy(setup):
    s = setup
    review(s)
    assert decide(s, evidence=proposal(s)["evidence_digest"]).status_code == 200
    with Session(s.assessment.app.state.engine) as session:
        row = session.get(PracticalSession, str(s.session_id))
        body = dict(
            scope="task",
            scope_id=row.stages[0]["revision_id"],
            task_key=row.stages[0]["task_key"],
            since=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
            until=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        )
    response = s.assessment.client.post("/v1/task-analytics/report", json=body, headers=s.author)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["sample_count"] == 1 and data["independent_label_count"] == 0
    assert data["target_distributions"][0]["buckets"][2]["count"] == 1
    assert data["correlation_count"] == 0  # One task cannot correlate with itself.
    assert str(s.candidate) not in response.text
    original = s.assessment.app.state.processing_access.check

    def deny(subject):
        if str(subject) == str(s.candidate):
            raise HTTPException(409)
        return original(subject)

    s.assessment.app.state.processing_access.check = deny
    response = s.assessment.client.post("/v1/task-analytics/report", json=body, headers=s.author)
    assert response.status_code == 200
    assert response.json()["sample_count"] == 0
    assert response.json()["excluded"]["restricted"] == 1
    with Session(s.assessment.app.state.engine) as session:
        assert len(list(session.scalars(select(GradeDecision)))) == 1


def test_live_prior_label_latest_attempt_and_technical_exclusion(setup):
    s = setup
    review(s)
    assert decide(s, evidence=proposal(s)["evidence_digest"]).status_code == 200
    with Session(s.assessment.app.state.engine) as session, session.begin():
        run = session.get(PracticalSession, str(s.session_id))
        decision = session.scalar(select(GradeDecision))
        prior_id = str(uuid4())
        session.add(
            PracticalSession(
                **{
                    column.name: getattr(run, column.name)
                    for column in PracticalSession.__table__.columns
                }
                | {
                    "session_id": prior_id,
                    "created_at": run.created_at - timedelta(days=2),
                    "stages": [],
                }
            )
        )
        session.add(
            GradeDecision(
                **{
                    column.name: getattr(decision, column.name)
                    for column in GradeDecision.__table__.columns
                }
                | {
                    "decision_id": str(uuid4()),
                    "session_id": prior_id,
                    "target_grade": "middle",
                    "created_at": run.created_at - timedelta(days=1),
                }
            )
        )
        body = dict(
            scope="task",
            scope_id=run.stages[0]["revision_id"],
            task_key=run.stages[0]["task_key"],
            since=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
            until=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        )
        run_copy = {
            column.name: getattr(run, column.name) for column in PracticalSession.__table__.columns
        }
        decision_copy = {
            column.name: getattr(decision, column.name)
            for column in GradeDecision.__table__.columns
        }
        later_id = str(uuid4())
        session.add(
            PracticalSession(
                **(
                    run_copy
                    | {"session_id": later_id, "created_at": run.created_at + timedelta(seconds=1)}
                )
            )
        )
        session.add(
            GradeDecision(**(decision_copy | {"decision_id": str(uuid4()), "session_id": later_id}))
        )
        broken_id = str(uuid4())
        session.add(
            PracticalSession(
                **(
                    run_copy
                    | {"session_id": broken_id, "created_at": run.created_at + timedelta(seconds=2)}
                )
            )
        )
        session.add(
            GradeDecision(
                **(
                    decision_copy
                    | {
                        "decision_id": str(uuid4()),
                        "session_id": broken_id,
                        "status": "technical_failure",
                        "score": None,
                    }
                )
            )
        )
    response = s.assessment.client.post("/v1/task-analytics/report", json=body, headers=s.author)
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["sample_count"] == 1
    assert data["independent_label_count"] == 1
    assert data["independent_distributions"][1]["count"] == 1
    assert data["excluded"]["superseded_attempts"] == 1
    assert data["excluded"]["technical_or_unscored"] == 1


def test_reference_version_and_family_scoping_empty_and_private(service, token):
    from tests.services.assessment.test_generation import create
    from tests.services.assessment.test_generation import setup as generation_setup

    target = generation_setup.__wrapped__(service, token)
    ref = create(target)
    for scope, key in (("reference_version", "version_id"), ("reference_family", "reference_id")):
        response = target.client.post(
            "/v1/task-analytics/report",
            headers=target.author,
            json=dict(
                scope=scope,
                scope_id=ref[key],
                since=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
                until=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
            ),
        )
        assert response.status_code == 200, response.text
        assert response.json()["sample_count"] == 0
        assert all(group["count"] == 0 for group in response.json()["target_distributions"])
        assert "no-store" in response.headers["Cache-Control"]
    from reverse_hr.services.assessment.domain.assessment_generation import GenerationReference

    with Session(target.app.state.engine) as session, session.begin():
        session.get(GenerationReference, ref["version_id"]).organization_id = str(uuid4())
    response = target.client.post(
        "/v1/task-analytics/report",
        headers=target.author,
        json=dict(
            scope="reference_version",
            scope_id=ref["version_id"],
            since=(datetime.now(UTC) - timedelta(days=1)).isoformat(),
            until=(datetime.now(UTC) + timedelta(days=1)).isoformat(),
        ),
    )
    assert response.status_code == 403
