"""Owner exports exclude assessment secrets even inside authored nested content."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy.orm import Session

from reverse_hr.coordination.rights_export import records
from reverse_hr.services.assessment.domain.assessment import ContentFamily, ContentRevision


def test_authored_assessment_export_never_includes_reference_answer_or_rubric(service):
    target = service("assessment")
    owner, family, revision = str(uuid4()), str(uuid4()), str(uuid4())
    with Session(target.app.state.engine) as session, session.begin():
        session.add(
            ContentFamily(
                family_id=family,
                name="Owned task",
                specialization="backend",
                grade="middle",
                version=1,
            )
        )
        session.flush()
        session.add(
            ContentRevision(
                revision_id=revision,
                family_id=family,
                number=1,
                status="draft",
                version=1,
                created_by=owner,
                created_at=datetime.now(UTC),
                content={
                    "tasks": [
                        {
                            "instruction": "Allowed own question",
                            "reference_answer": "PRIVATE-ANSWER",
                            "rubric": [{"description": "PRIVATE-RUBRIC"}],
                            "nested": {"private_rubric": "PRIVATE-NESTED"},
                        }
                    ]
                },
            )
        )
    with Session(target.app.state.engine) as session:
        exported = list(records(session, "assessment", owner))
        assert not list(records(session, "assessment", uuid4()))
    rendered = json.dumps(exported)
    assert "Allowed own question" in rendered
    assert "PRIVATE" not in rendered
