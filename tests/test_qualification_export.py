"""Reviewed rubric percentages are signed, immutable, and exclude raw artifacts."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session
from test_assessment_grades import decide, proposal, review
from test_assessment_grades import setup as grade_fixture
from test_event_transport import signatures as signatures_fixture

from reverse_hr.confirmed_grade_access import REQUEST, DecisionReceipt, DecisionRequest
from reverse_hr.db import Outbox
from reverse_hr.domains.assessment_grades import CandidateGrade, GradeDecision
from reverse_hr.events import EventEnvelope
from reverse_hr.processing_access import sign

assessment_setup = grade_fixture
signatures = signatures_fixture


def test_signed_qualification_is_bound_to_immutable_reviewed_decision(assessment_setup, signatures):
    s = assessment_setup
    review(s)
    result = proposal(s)
    assert decide(s, evidence=result["evidence_digest"]).status_code == 200
    with Session(s.assessment.app.state.engine) as session:
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in session.scalars(select(Outbox))
            if row.envelope["event_type"] == "assessment.grade_decision_recorded.v1"
        )
        decision = session.get(GradeDecision, str(event.payload["decision_id"]))
        scores = dict(decision.competency_scores)

    def fetch():
        body = DecisionRequest(
            **event.payload,
            session_version=event.aggregate_version,
            nonce=uuid4(),
            issued_at=datetime.now(UTC),
        )
        response = s.assessment.client.post(
            "/internal/v1/confirmed-grade",
            json=body.model_dump(mode="json"),
            headers={"X-HR-Signature": sign(signatures["candidate"], REQUEST, body)},
        )
        assert response.status_code == 200, response.text
        return DecisionReceipt.model_validate_json(response.content).decision

    first = fetch()
    assert first.qualification is not None
    assert first.qualification.competency_scores == scores
    assert 0 <= first.qualification.score <= 100
    assert (
        not {"stages", "reason", "reviewer_id", "tests"} & first.qualification.model_dump().keys()
    )
    # A later unrelated grade transition must not mutate a previously signed event payload.
    with Session(s.assessment.app.state.engine) as session, session.begin():
        grade = session.get(
            CandidateGrade, (str(event.payload["candidate_id"]), first.specialization)
        )
        grade.change_available_at = datetime.now(UTC) + timedelta(days=400)
    assert fetch() == first
