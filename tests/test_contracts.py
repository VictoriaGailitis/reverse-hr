import json
from pathlib import Path
from uuid import uuid4

from jsonschema import Draft202012Validator, FormatChecker

from reverse_hr.app import create_app
from reverse_hr.events import EventEnvelope
from reverse_hr.settings import SIGNING_SERVICES, Settings


def test_exported_runtime_contracts_match_code():
    for service in SIGNING_SERVICES:
        app = create_app(Settings(service_name=service))
        try:
            expected = json.loads(Path(f"contracts/{service}.openapi.json").read_text())
            assert expected == app.openapi()
        finally:
            app.state.engine.dispose()


def test_event_schema_and_synthetic_example():
    schema = json.loads(Path("contracts/event-envelope.schema.json").read_text())
    assert schema == EventEnvelope.model_json_schema()
    Draft202012Validator.check_schema(schema)
    example = EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={"candidate_id": uuid4(), "organization_id": uuid4()},
    ).model_dump(mode="json")
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    validator.validate(example)
    example["payload"]["email"] = "sensitive@example.test"
    assert list(validator.iter_errors(example))


def test_proposed_command_contracts_require_identity_and_concurrency():
    schema = json.loads(Path("contracts/first-scenario.proposed.openapi.json").read_text())
    assert schema["info"]["version"].endswith("-draft")
    for path, methods in schema["paths"].items():
        for method, operation in methods.items():
            assert operation["security"]
            for code in (401, 403, 404, 409, 422, 503):
                assert str(code) in operation["responses"]
            if method in ("post", "put"):
                headers = {
                    param["name"]: param
                    for param in operation["parameters"]
                    if param["in"] == "header"
                }
                assert headers["Idempotency-Key"]["required"]
                if "{" in path or method == "put":
                    assert headers["If-Match"]["required"]
