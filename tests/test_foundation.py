from uuid import uuid4

import pytest
from alembic import command
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session

from reverse_hr.app import create_app
from reverse_hr.contracts import SalaryRange
from reverse_hr.db import Inbox, Outbox, consume_once, enqueue
from reverse_hr.events import EventEnvelope
from reverse_hr.migrate import migration_config
from reverse_hr.settings import SERVICES, Settings


@pytest.fixture
def app(tmp_path, monkeypatch):
    url = f"sqlite:///{tmp_path}/service.db"
    monkeypatch.setenv("HR_DATABASE_URL", url)
    application = create_app(Settings(database_url=url))
    yield application
    application.state.engine.dispose()


def migrate():
    command.upgrade(migration_config(), "head")


def test_readiness_requires_migration_and_trace_id(app):
    with TestClient(app) as client:
        trace = str(uuid4())
        response = client.get("/health/ready", headers={"X-Request-ID": trace})
        assert response.status_code == 503
        assert response.json()["trace_id"] == trace
        assert response.headers["X-Request-ID"] == trace
        assert client.get("/health/live").status_code == 200
        migrate()
        assert client.get("/health/ready").status_code == 200
        assert "hr_http_requests_total" in client.get("/metrics").text


@pytest.mark.parametrize("service", SERVICES)
def test_each_service_has_independent_identity(service):
    app = create_app(Settings(service_name=service, database_url="sqlite://"))
    with TestClient(app) as client:
        assert client.get("/health/live").json()["service"] == service
        assert "first scenario" not in client.get("/openapi.json").text
        assert client.get("/v1/candidates/me").status_code == (
            401 if service == "candidate" else 404
        )


def test_error_does_not_leak_internal_detail(app):
    @app.get("/private-failure")
    def fail():
        raise HTTPException(403, "secret token and contact data")

    @app.get("/unexpected-failure")
    def unexpected():
        raise RuntimeError("postgresql://user:password@host/db")

    @app.get("/validate")
    def validate(count: int):
        return count

    with TestClient(app) as client:
        assert "secret" not in client.get("/private-failure").text
        failure = client.get("/unexpected-failure")
        assert failure.status_code == 500
        assert "password" not in failure.text
        response = client.get("/validate?count=token-secret")
        assert response.status_code == 422
        assert response.json()["fields"] == ["query.count"]
        assert "token-secret" not in response.text
        UUID = type(uuid4())
        UUID(
            client.get("/health/live", headers={"X-Request-ID": "malformed"}).headers[
                "X-Request-ID"
            ]
        )


def event():
    return EventEnvelope(
        event_type="hiring.invitation_accepted.v1",
        producer="hiring",
        correlation_id=uuid4(),
        aggregate_id=uuid4(),
        aggregate_version=1,
        payload={"candidate_id": uuid4(), "organization_id": uuid4()},
    )


def test_outbox_and_inbox_rollback_and_duplicate(app):
    migrate()
    engine = app.state.engine
    message = event()
    with pytest.raises(RuntimeError), Session(engine) as session, session.begin():
        enqueue(session, message)
        session.flush()
        raise RuntimeError("abort business transaction")
    with Session(engine) as session:
        assert session.scalar(select(Outbox)) is None
    with Session(engine) as session, session.begin():
        enqueue(session, message)
    calls = []
    with Session(engine) as session, session.begin():
        assert consume_once(session, "privacy", message, lambda *_: calls.append(1))
    with Session(engine) as session, session.begin():
        assert not consume_once(session, "privacy", message, lambda *_: calls.append(2))
    assert calls == [1]
    failed = event()

    def fail(session, incoming):
        enqueue(session, incoming)
        raise RuntimeError("handler failed")

    with pytest.raises(RuntimeError), Session(engine) as session, session.begin():
        consume_once(session, "privacy", failed, fail)
    with Session(engine) as session:
        assert session.get(Inbox, ("privacy", str(failed.event_id))) is None
        assert session.get(Outbox, str(failed.event_id)) is None


def test_migration_downgrade_and_reapply(app):
    migrate()
    command.downgrade(migration_config(), "base")
    assert "outbox" not in inspect(app.state.engine).get_table_names()
    migrate()
    assert "outbox" in inspect(app.state.engine).get_table_names()


def test_contract_rejects_inverted_salary_and_pii_event():
    with pytest.raises(ValidationError):
        SalaryRange(minimum=200000, maximum=100000, tax_basis="gross")
    with pytest.raises(ValidationError):
        EventEnvelope(**(event().model_dump() | {"payload": {"email": "private@example.test"}}))
