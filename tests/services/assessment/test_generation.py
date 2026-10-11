"""Authoring and provider lifecycle on migrated owner databases, synthetic provider only."""

import copy
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.services.assessment.domain.assessment_generation import (
    GenerationJob,
    GenerationPreview,
    GenerationReference,
)
from reverse_hr.services.assessment.domain.assessment_sessions import PlanVersion
from reverse_hr.services.assessment.generation_worker import run_one
from reverse_hr.shared.llm_configuration import GatewayConfiguration
from tests.shared.test_access import headers

REFERENCE = dict(
    name="Оригинальное объяснение отказоустойчивости",
    format="voice",
    specialization="backend",
    grade="junior",
    description=(
        "Объясните обработку сбоев в собственной системе уведомлений и обоснуйте принятые решения."
    ),
    required_constraints=["Не раскрывать контакты"],
    allowed_variations=["Название предметной области"],
    forbidden_changes=["Сложность и критерии оценки"],
    parameters={"domain": ["заказы", "сообщения"]},
    competencies=[dict(key="design", description="Обоснование решений")],
    rubric=[
        dict(
            key="quality",
            competency="design",
            description="Корректность объяснения",
            points=100,
            evidence="timestamped_recording",
        )
    ],
    duration_seconds=600,
    pool_size=2,
    max_exposures=2,
)


@pytest.fixture
def setup(service, token):
    target = service("assessment")
    settings = target.app.state.settings
    settings.assessment_generation_enabled = True
    settings.assessment_generation_model = "synthetic-original-v1"
    settings.assessment_generation_config = GatewayConfiguration(
        origin="https://generator.invalid",
        max_input_tokens=32768,
        max_output_tokens=2048,
        input_microusd_per_million_tokens=1000,
        output_microusd_per_million_tokens=1000,
        stage_budget_microusd=300,
    )
    author, approver, candidate = uuid4(), uuid4(), uuid4()
    target.author = token(author, ("content_admin",), amr=["mfa"])
    target.approver = token(approver, ("content_admin",), amr=["mfa"])
    target.candidate = token(candidate)
    target.author_id = author
    target.request = SimpleNamespace(app=target.app, state=SimpleNamespace(trace_id=uuid4()))
    target.gateway = SimpleNamespace(
        model=settings.assessment_generation_model,
        configuration=settings.assessment_generation_config.model_dump(mode="json"),
        generate=lambda spec: dict(
            task=dict(
                key="original",
                format=spec["reference"]["format"],
                instruction=(
                    "Не раскрывать контакты. Объясните повторную доставку "
                    "сообщений в системе уведомлений."
                ),
                duration_seconds=600,
                reference_answer="Оригинальное описание дедупликации и повторной доставки",
                rubric=spec["reference"]["rubric"],
            ),
            suite=None,
        ),
        validate=lambda *args: True,
    )
    return target


def create(s, body=None):
    reply = s.client.post(
        "/v1/assessment-generation/references",
        json=body or REFERENCE,
        headers=headers(s.author, "reference"),
    )
    assert reply.status_code == 201, reply.text
    return reply.json()


def trial(s, ref):
    route = f"/v1/assessment-generation/references/{ref['version_id']}/preview"
    result = s.client.post(
        route,
        json=dict(
            scenario="Проверить систему повторной доставки заказов", parameters={"domain": "заказы"}
        ),
        headers=headers(s.author, "preview"),
    )
    assert result.status_code == 201, result.text
    preview = result.json()
    body = dict(preview_id=preview["preview_id"], specification_digest=preview["digest"])
    result = s.client.post(
        "/v1/assessment-generation/generate", json=body, headers=headers(s.author, "trial")
    )
    assert result.status_code == 202, result.text
    return preview, body, result.json()


def jobs(s, ref):
    return s.client.get(
        f"/v1/assessment-generation/references/{ref['version_id']}/jobs", headers=s.author
    ).json()


def test_preview_confirmation_and_independent_publication(setup):
    s = setup
    ref = create(s)
    preview, body, job = trial(s, ref)
    assert preview["specification"]["reference_digest"] == ref["digest"]
    assert (
        s.client.post(
            "/v1/assessment-generation/generate", json=body, headers=headers(s.author, "trial")
        ).json()
        == job
    )
    assert (
        s.client.post(
            "/v1/assessment-generation/generate",
            json=body,
            headers=headers(s.author, "trial-other"),
        ).status_code
        == 409
    )
    assert run_one(s.request, s.gateway)
    assert jobs(s, ref)[0]["status"] == "ready"
    assert s.client.get("/v1/assessment-generation/offers", headers=s.candidate).json() == []
    path = f"/v1/assessment-generation/references/{ref['version_id']}/publish"
    assert (
        s.client.post(
            path,
            json={"reason": "Проверена собственная методика"},
            headers=headers(s.author, "publish-self", 1),
        ).status_code
        == 403
    )
    result = s.client.post(
        path,
        json={"reason": "Независимо проверена собственная методика"},
        headers=headers(s.approver, "publish", 1),
    )
    assert result.status_code == 200, result.text
    offers = s.client.get("/v1/assessment-generation/offers", headers=s.candidate).json()
    assert len(offers) == 1 and not offers[0]["scored"]
    # Replenishment is enabled only after reference publication.
    assert run_one(s.request, s.gateway)
    with Session(s.app.state.engine) as db:
        assert len(list(db.scalars(select(GenerationJob)))) == 2


def test_parameter_bounds_expired_preview_and_original_text(setup):
    s = setup
    ref = create(s)
    path = f"/v1/assessment-generation/references/{ref['version_id']}/preview"
    assert (
        s.client.post(
            path,
            json=dict(scenario="Новый вариант сценария", parameters={"domain": "чужое значение"}),
            headers=headers(s.author, "wrong-param"),
        ).status_code
        == 422
    )
    preview, body, _ = trial(s, ref)
    with Session(s.app.state.engine) as db, db.begin():
        item = db.get(GenerationPreview, preview["preview_id"])
        item.generation_id = None
        item.expires_at = datetime.now(UTC) - timedelta(minutes=1)
    assert (
        s.client.post(
            "/v1/assessment-generation/generate", json=body, headers=headers(s.author, "expired")
        ).status_code
        == 409
    )
    assert (
        s.client.post(
            "/v1/assessment-generation/references",
            json=REFERENCE | {"description": "Загрузить материал с https://external.invalid/"},
            headers=headers(s.author, "external"),
        ).status_code
        == 422
    )
    assert (
        s.client.post(
            "/v1/assessment-generation/references",
            json=REFERENCE,
            headers=headers(s.candidate, "candidate-author"),
        ).status_code
        == 403
    )


def test_semantic_rejection_and_revocation_during_provider_call(setup):
    s = setup
    ref = create(s)
    trial(s, ref)
    s.gateway.validate = lambda *args: False
    assert run_one(s.request, s.gateway)
    assert jobs(s, ref)[0]["status"] == "rejected"
    with Session(s.app.state.engine) as db:
        assert db.scalar(select(PlanVersion)) is None
    with Session(s.app.state.engine) as db, db.begin():
        job = db.scalar(select(GenerationJob))
        job.status = "pending"
        job.available_at = datetime.now(UTC) - timedelta(seconds=1)

    def revoked(*args):
        with Session(s.app.state.engine) as db, db.begin():
            db.get(GenerationReference, ref["version_id"]).status = "retired"
        return True

    s.gateway.validate = revoked
    assert run_one(s.request, s.gateway)
    assert jobs(s, ref)[0]["status"] == "cancelled"


def test_new_versions_preserve_identity_and_old_snapshot(setup):
    s = setup
    ref = create(s)
    path = f"/v1/assessment-generation/references/{ref['version_id']}/versions"
    assert (
        s.client.post(
            path, json=REFERENCE | {"format": "vcv"}, headers=headers(s.author, "format-change", 1)
        ).status_code
        == 422
    )
    changed = copy.deepcopy(REFERENCE)
    changed["description"] += " Уточните способ наблюдения за очередью."
    result = s.client.post(path, json=changed, headers=headers(s.author, "edit", 1))
    assert result.status_code == 201, result.text
    assert result.json()["reference_id"] == ref["reference_id"] and result.json()["number"] == 2
    with Session(s.app.state.engine) as db:
        assert (
            db.get(GenerationReference, ref["version_id"]).data["description"]
            == REFERENCE["description"]
        )


def test_calibrated_reference_binds_cloned_policy_at_publication(setup):
    from tests.services.assessment.test_assessment_grades import calibration

    s = setup
    ref = create(s)
    trial(s, ref)
    assert run_one(s.request, s.gateway)
    plan = jobs(s, ref)[0]["plan_version_id"]
    rules = dict(
        weights={"design": 100},
        minimums={"design": 60},
        pass_score=70,
        retry_seconds=3600,
        grade_change_seconds=86400,
        automatic_decisions=True,
        required_llm_model="synthetic-calibrated-v1",
        required_llm_prompt_digest="c" * 64,
        generation_reference_id=ref["version_id"],
    )
    reply = s.client.post(
        "/v1/grade-policies",
        json=dict(plan_version_id=plan, rules=rules),
        headers=headers(s.author, "generation-policy"),
    )
    assert reply.status_code == 201, reply.text
    policy = reply.json()
    labels = calibration()
    for item in labels["cases"]:
        item["scores"] = {"design": item["scores"]["structure"]}
    reply = s.client.post(
        f"/v1/grade-policies/{policy['policy_id']}/approve",
        json=labels,
        headers=headers(s.approver, "generation-calibration", 1),
    )
    assert reply.status_code == 200, reply.text
    reply = s.client.post(
        f"/v1/assessment-generation/references/{ref['version_id']}/grading-policy",
        json=dict(grade_policy_id=policy["policy_id"]),
        headers=headers(s.author, "bind-policy", 1),
    )
    assert reply.status_code == 200, reply.text
    reply = s.client.post(
        f"/v1/assessment-generation/references/{ref['version_id']}/publish",
        json={"reason": "Independent original reference approval with synthetic labels"},
        headers=headers(s.approver, "publish-scored", 2),
    )
    assert reply.status_code == 200, reply.text
    assert jobs(s, ref)[0]["grade_policy_id"] != policy["policy_id"]
    assert s.client.get("/v1/assessment-generation/offers", headers=s.candidate).json()[0]["scored"]
    reply = s.client.post(
        "/v1/assessment-generation/sessions",
        json=dict(version_id=ref["version_id"], assessment_consent_id=str(uuid4())),
        headers=headers(s.candidate, "generated-session"),
    )
    assert reply.status_code == 201, reply.text
    from reverse_hr.services.assessment.domain.assessment_sessions import PracticalSession

    with Session(s.app.state.engine) as db:
        assert (
            db.get(PracticalSession, reply.json()["session_id"]).grade_policy_id
            == jobs(s, ref)[0]["grade_policy_id"]
        )


def test_privacy_removes_original_text_outputs_and_replay_access(setup):
    from reverse_hr.services.assessment.domain.assessment_sessions import process_deletion_request
    from tests.services.code_runner.test_code_runner import deletion

    s = setup
    ref = create(s)
    trial(s, ref)
    assert run_one(s.request, s.gateway)
    with Session(s.app.state.engine) as db, db.begin():
        assert process_deletion_request(db, deletion(s.author_id))
    with Session(s.app.state.engine) as db:
        assert db.scalar(select(GenerationReference)) is None
        assert db.scalar(select(GenerationPreview)) is None
        assert db.scalar(select(GenerationJob)) is None
    assert s.client.get(
        f"/v1/assessment-generation/references/{ref['version_id']}/jobs", headers=s.author
    ).status_code in {404, 409}


def test_expired_provider_lease_discards_late_output(setup):
    s = setup
    ref = create(s)
    trial(s, ref)

    def expire(*args):
        with Session(s.app.state.engine) as db, db.begin():
            db.scalar(select(GenerationJob)).lease_until = datetime.now(UTC) - timedelta(seconds=1)
        return True

    s.gateway.validate = expire
    assert run_one(s.request, s.gateway)
    with Session(s.app.state.engine) as db:
        job = db.scalar(select(GenerationJob))
        assert job.output is None and job.status == "pending"
        assert job.error == "provider_lease_expired" and db.scalar(select(PlanVersion)) is None


def test_company_trial_is_not_an_approved_assignment_until_reference_publication(setup, token):
    from reverse_hr.services.assessment.domain.company_tasks import CompanyProposal

    s = setup
    organization = uuid4()
    s.author = token(s.author_id, ("employer",), amr=["mfa"])
    s.app.state.market_access = SimpleNamespace(require=lambda *args, **kwargs: None)
    ref = create(s, REFERENCE | {"organization_id": str(organization)})
    trial(s, ref)
    assert run_one(s.request, s.gateway)
    with Session(s.app.state.engine) as db:
        assert db.scalar(select(CompanyProposal)) is None
    reply = s.client.post(
        f"/v1/assessment-generation/references/{ref['version_id']}/publish",
        json={"reason": "Own company original reference approval"},
        headers=headers(s.author, "company-publish", 1),
    )
    assert reply.status_code == 200, reply.text
    with Session(s.app.state.engine) as db:
        proposal = db.scalar(select(CompanyProposal))
        assert proposal.status == "approved" and proposal.organization_id == str(organization)
        assert db.scalar(select(GenerationJob)).grade_policy_id is None
    assert s.client.get("/v1/assessment-generation/offers", headers=s.candidate).json() == []
