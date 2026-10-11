"""Synthetic provider proposals passed through signed evidence and citation validators."""

from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.services.evaluation.domain.evaluation import EvaluationIntake
from reverse_hr.services.evaluation.domain.evaluation_review import ReviewCommand, ReviewRecord
from reverse_hr.services.evaluation.evaluation_automatic import AutomaticStageReview, run_one
from reverse_hr.services.evaluation.evaluation_llm import ModelReply
from tests.services.evaluation.test_evaluation_llm import run as model_run
from tests.services.evaluation.test_evaluation_llm import setup as setup
from tests.services.evaluation.test_evaluation_llm import signatures as signatures
from tests.services.evaluation.test_evaluation_review import body


def tick(s, signatures, integrity=None):
    _, target, _ = s
    state = target.app.state
    return run_one(
        state.engine,
        state.settings,
        state.material_access,
        state.artifact_access,
        state.processing_access,
        signatures["evaluation"],
        integrity,
    )


def provider(original, points=(50, 30)):
    return SimpleNamespace(
        evaluate=lambda **kwargs: ModelReply(
            proposal=ReviewCommand.model_validate(body(original, points)),
            input_tokens=123,
            output_tokens=45,
            cost_microusd=67,
        )
    )


def test_two_consistent_proposals_create_one_evidence_checked_review(setup, signatures):
    original, target, stage = setup
    assert tick(setup, signatures)
    assert model_run(setup, provider(original))
    assert tick(setup, signatures)
    assert model_run(setup, provider(original, (48, 30)))
    assert tick(setup, signatures)
    assert not tick(setup, signatures)
    with Session(target.app.state.engine) as db:
        review = db.scalar(select(ReviewRecord))
        assert review.origin == "automatic" and review.score == 78
        assert db.get(EvaluationIntake, str(stage)).score == 78


def test_disagreement_routes_to_human_without_zero_score(setup, signatures):
    original, target, stage = setup
    assert tick(setup, signatures) and model_run(setup, provider(original))
    assert tick(setup, signatures) and model_run(setup, provider(original, (30, 20)))
    assert tick(setup, signatures)
    with Session(target.app.state.engine) as db:
        assert db.scalar(select(ReviewRecord)) is None
        assert db.get(EvaluationIntake, str(stage)).score is None
        state = db.get(AutomaticStageReview, str(stage))
        assert state.status == "review_pending" and state.reason == "model_disagreement"


def test_integrity_concern_never_lowers_competency_score(setup, signatures):
    _, target, stage = setup
    integrity = SimpleNamespace(
        fetch=lambda *args: SimpleNamespace(status="concern", flags=["focus"])
    )
    assert tick(setup, signatures, integrity)
    with Session(target.app.state.engine) as db:
        assert db.get(EvaluationIntake, str(stage)).score is None
        assert db.get(AutomaticStageReview, str(stage)).reason == "additional_verification_required"


def test_missing_provider_enters_human_queue(setup, signatures):
    _, target, stage = setup
    target.app.state.settings.evaluation_llm_enabled = False
    assert tick(setup, signatures)
    with Session(target.app.state.engine) as db:
        assert db.get(EvaluationIntake, str(stage)).score is None
        assert db.get(AutomaticStageReview, str(stage)).reason == "model_unavailable"
