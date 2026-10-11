"""Generated code travels through real signed RPC/queue; sandbox/probe are synthetic."""

from types import SimpleNamespace
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.contracts.events import EventEnvelope
from reverse_hr.protocols.generated_validation import GeneratedValidationAccess
from reverse_hr.services.assessment.domain.assessment_generation import GenerationJob
from reverse_hr.services.assessment.generation_worker import run_one
from reverse_hr.services.code_runner.generated_validation import dispatch_one, receive
from reverse_hr.shared.db import Outbox
from reverse_hr.shared.llm_configuration import GatewayConfiguration
from tests.services.assessment.test_generation import REFERENCE
from tests.services.code_runner.test_validation_queue import setup as setup
from tests.services.code_runner.test_validation_queue import signatures as signatures
from tests.services.code_runner.test_validation_queue import tick
from tests.shared.test_access import headers


def test_generated_suite_requires_signed_native_validation_before_ready(setup, token, monkeypatch):
    s = setup
    for _ in range(len(s.plan.inputs) + 3):
        assert tick(s)
    settings = s.assessment.app.state.settings
    settings.assessment_trusted_runtimes = [s.policy]
    settings.assessment_generation_enabled = True
    settings.assessment_generation_model = "synthetic-original-code-v1"
    settings.assessment_generation_config = GatewayConfiguration(
        origin="https://generator.invalid",
        max_input_tokens=32768,
        max_output_tokens=2048,
        input_microusd_per_million_tokens=1000,
        output_microusd_per_million_tokens=1000,
        stage_budget_microusd=300,
    )
    auth = token(UUID(str(s.owner)), ("content_admin",), amr=["mfa"])
    ref = REFERENCE | dict(
        format="code",
        competencies=[dict(key="structure", description="Корректность")],
        rubric=[
            dict(
                key="shape",
                competency="structure",
                description="Корректность",
                points=100,
                evidence="test_result",
            )
        ],
    )
    reply = s.assessment.client.post(
        "/v1/assessment-generation/references",
        json=ref,
        headers=headers(auth, "generated-reference"),
    )
    assert reply.status_code == 201, reply.text
    ref = reply.json()
    reply = s.assessment.client.post(
        f"/v1/assessment-generation/references/{ref['version_id']}/preview",
        json=dict(
            scenario="Проверить оригинальный алгоритм обработки данных",
            parameters={"domain": "заказы"},
        ),
        headers=headers(auth, "generated-preview"),
    )
    assert reply.status_code == 201, reply.text
    preview = reply.json()
    reply = s.assessment.client.post(
        "/v1/assessment-generation/generate",
        json=dict(preview_id=preview["preview_id"], specification_digest=preview["digest"]),
        headers=headers(auth, "generated-trial"),
    )
    assert reply.status_code == 202, reply.text
    reference = next(f.content for f in s.definition.reference.files if f.path == "main.py")
    gateway = SimpleNamespace(
        model=settings.assessment_generation_model,
        configuration=settings.assessment_generation_config.model_dump(mode="json"),
        generate=lambda spec: dict(
            task=dict(
                key="generated",
                format="code",
                instruction="Не раскрывать контакты. Реализовать обработку данных по спецификации.",
                duration_seconds=600,
                reference_answer=reference,
                rubric=spec["reference"]["rubric"],
            ),
            suite=s.definition.model_dump(mode="json"),
        ),
        validate=lambda *args: True,
    )
    request = SimpleNamespace(app=s.assessment.app, state=SimpleNamespace(trace_id=uuid4()))
    assert run_one(request, gateway)
    with Session(s.assessment.app.state.engine) as db:
        job = db.get(GenerationJob, reply.json()["generation_id"])
        assert job.status == "validating" and job.plan_version_id is None
        event = next(
            EventEnvelope.model_validate(row.envelope)
            for row in db.scalars(select(Outbox))
            if row.envelope["event_type"] == "assessment.generated_validation_requested.v1"
        )
    assert set(event.payload) == {"candidate_id", "generation_id"}

    def send(self, route, raw, signature, **kwargs):
        response = s.assessment.client.post(
            "/internal/v1/generated-validation",
            content=raw,
            headers={"Content-Type": "application/json", "X-HR-Signature": signature},
        )
        assert response.status_code == 200, response.text
        return response.content, response.headers["X-HR-Signature"]

    monkeypatch.setattr(GeneratedValidationAccess, "_send", send)
    with Session(s.engine) as db, db.begin():
        assert receive(db, event)
        assert not receive(db, event)
    assert dispatch_one(s.engine, s.processing, s.access, s.executor, s.signatures["code-runner"])
    access = GeneratedValidationAccess(s.executor.settings)
    access._signatures = s.signatures["code-runner"]
    s.plan = access.fetch(UUID(str(s.owner)), event.payload["generation_id"])
    for _ in range(len(s.plan.inputs) + 3):
        assert tick(s)
    assert run_one(request, gateway)
    with Session(s.assessment.app.state.engine) as db:
        job = db.get(GenerationJob, str(event.payload["generation_id"]))
        assert job.status == "ready" and job.plan_version_id
