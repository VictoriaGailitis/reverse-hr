from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.services.evaluation.domain.evaluation import (
    EvaluationIntake,
    process_deletion_request,
)
from reverse_hr.services.evaluation.evaluation_automatic import AutomaticStageReview
from reverse_hr.services.evaluation.evaluation_llm import ModelAttempt
from reverse_hr.services.evaluation.evaluation_risk import (
    EvaluationRisk,
    register,
    requires_verification,
)
from reverse_hr.shared.db import Outbox
from tests.services.evaluation.test_automatic_evaluation import setup as setup
from tests.services.evaluation.test_automatic_evaluation import signatures as signatures
from tests.services.evaluation.test_automatic_evaluation import tick
from tests.services.evaluation.test_evaluation_llm import enqueue, run
from tests.shared.test_access import headers


def flag(s, codes=("instruction_override",)):
    _, target, stage = s
    with Session(target.app.state.engine) as db, db.begin():
        intake = db.get(EvaluationIntake, str(stage))
        register(db, intake, codes)
        return intake.candidate_id


def test_persistent_dedup_risk_blocks_model_and_automatic_grade(setup, signatures):
    candidate = flag(setup)
    flag(setup)
    assert tick(setup, signatures)
    original, target, stage = setup
    with Session(target.app.state.engine) as db:
        assert len(list(db.scalars(select(EvaluationRisk)))) == 1
        assert db.get(AutomaticStageReview, str(stage)).reason == "additional_verification_required"
        assert db.get(EvaluationIntake, str(stage)).score is None
        assert db.scalar(select(ModelAttempt)) is None
        assert requires_verification(db, candidate)
    # Explicit reviewer model requests also stop at the worker before any provider call.
    assert enqueue(setup).status_code == 202
    gateway = type(
        "Forbidden",
        (),
        {"evaluate": lambda **kw: (_ for _ in ()).throw(AssertionError("Must not call model"))},
    )()
    assert run(setup, gateway)
    with Session(target.app.state.engine) as db:
        assert db.scalar(select(ModelAttempt)).status == "blocked"
    response = target.client.get("/v1/evaluation-risks/queue", headers=original[1])
    assert response.status_code == 200 and len(response.json()["items"]) == 1, response.text


def test_independent_decision_cas_replay_and_evidence_required(setup, signatures):
    candidate = flag(setup)
    original, target, stage = setup
    path = f"/v1/evaluation-risks/{stage}/decision"
    body = dict(action="require_verification", reason="Check separately using fresh evidence")
    reply = target.client.post(path, json=body, headers=headers(original[1], "risk", 1))
    assert reply.status_code == 200, reply.text
    assert reply.json()["status"] == "verification_required"
    assert (
        target.client.post(path, json=body, headers=headers(original[1], "risk", 1)).status_code
        == 200
    )
    assert (
        target.client.post(path, json=body, headers=headers(original[1], "stale", 1)).status_code
        == 409
    )
    bad = target.client.post(
        path,
        json=dict(
            action="complete_verification",
            reason="Require a distinct task",
            verification_stage_id=str(stage),
        ),
        headers=headers(original[1], "same-stage", 2),
    )
    assert bad.status_code == 422
    missing = target.client.post(
        path,
        json=dict(
            action="complete_verification",
            reason="Require real reviewed evidence",
            verification_stage_id=str(uuid4()),
        ),
        headers=headers(original[1], "missing", 2),
    )
    assert missing.status_code == 409
    reply = target.client.post(
        path,
        json=dict(action="dismiss", reason="A legitimate security demonstration"),
        headers=headers(original[1], "dismiss", 2),
    )
    assert reply.status_code == 200 and reply.json()["status"] == "dismissed", reply.text
    with Session(target.app.state.engine) as db:
        assert not requires_verification(db, candidate)
    assert tick(setup, signatures)  # model proposals can resume after independent dismissal


def test_privacy_erases_risk_and_queued_events(setup):
    candidate = flag(setup)
    _, target, _ = setup
    request_id = uuid4()
    event = EventEnvelope(
        producer="privacy",
        event_type="privacy.deletion_requested.v1",
        aggregate_id=request_id,
        aggregate_version=1,
        correlation_id=uuid4(),
        payload={"candidate_id": UUID(candidate), "request_id": request_id},
    )
    with Session(target.app.state.engine) as db, db.begin():
        process_deletion_request(db, event)
    with Session(target.app.state.engine) as db:
        assert db.scalar(select(EvaluationRisk)) is None
        assert not any(
            r.envelope["event_type"] == "evaluation.risk_detected.v1"
            for r in db.scalars(select(Outbox))
        )


def test_fresh_human_verification_releases_only_linked_risk(setup):
    from datetime import UTC, datetime

    from reverse_hr.services.evaluation.domain.evaluation_review import ReviewRecord
    from tests.services.evaluation.test_evaluation_review import body

    candidate = flag(setup)
    original, target, stage = setup
    verification = uuid4()
    with Session(target.app.state.engine) as db, db.begin():
        intake = db.get(EvaluationIntake, str(stage))
        values = {
            column.name: getattr(intake, column.name)
            for column in EvaluationIntake.__table__.columns
        }
        values.update(
            stage_id=str(verification),
            received_at=datetime.now(UTC),
            review_number=1,
            score=80,
            status="reviewed",
        )
        db.add(EvaluationIntake(**values))
        db.flush()
        db.add(
            ReviewRecord(
                review_id=str(uuid4()),
                stage_id=str(verification),
                candidate_id=candidate,
                reviewer_id=str(original[2]),
                number=1,
                intake_version=1,
                origin="human",
                decisions=body(original)["decisions"],
                score=80,
                reason="Independent extra evidence review",
                created_at=datetime.now(UTC),
            )
        )
    reply = target.client.post(
        f"/v1/evaluation-risks/{stage}/decision",
        headers=headers(original[1], "verification", 1),
        json=dict(
            action="complete_verification",
            reason="Separate task checked independently",
            verification_stage_id=str(verification),
        ),
    )
    assert reply.status_code == 200 and reply.json()["status"] == "verified", reply.text
    with Session(target.app.state.engine) as db:
        assert not requires_verification(db, candidate)
        assert db.get(EvaluationIntake, str(stage)).score is None
