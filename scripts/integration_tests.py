"""Run tests against the local project's disposable PostgreSQL/RabbitMQ without logging secrets."""

import argparse
import logging
import os
from urllib.parse import quote

import pytest
from dotenv import dotenv_values
from sqlalchemy import text

from reverse_hr.platform.settings import Settings
from reverse_hr.shared.db import make_engine
from reverse_hr.shared.event_transport import connect

parser = argparse.ArgumentParser()
parser.add_argument("--postgres-port", type=int, default=55329)
parser.add_argument("--amqp-port", type=int, default=55330)
args = parser.parse_args()
logging.disable(logging.CRITICAL)
values = dotenv_values(".env")
for service in (
    "candidate",
    "privacy",
    "hiring",
    "employer",
    "assessment",
    "coding-workspace",
    "code-runner",
):
    prefix = service.upper().replace("-", "_")
    password = quote(values[f"{prefix}_DB_PASSWORD"], safe="")
    database = service.replace("-", "_")
    url = f"postgresql+psycopg://{database}:{password}@localhost:{args.postgres_port}/{database}"
    os.environ[f"HR_TEST_{prefix}_DATABASE_URL"] = url
    if service == "candidate":
        os.environ["HR_TEST_POSTGRES_URL"] = url
    elif service == "privacy":
        os.environ["HR_TEST_PRIVACY_POSTGRES_URL"] = url
    password = quote(values[f"{prefix}_AMQP_PASSWORD"], safe="")
    os.environ[f"HR_TEST_{prefix}_AMQP_URL"] = (
        f"amqp://{service}:{password}@localhost:{args.amqp_port}/%2F"
    )
try:
    for service in (
        "candidate",
        "privacy",
        "hiring",
        "employer",
        "assessment",
        "coding-workspace",
        "code-runner",
    ):
        prefix = service.upper().replace("-", "_")
        config = Settings(
            service_name=service,
            database_url=os.environ[f"HR_TEST_{prefix}_DATABASE_URL"],
            amqp_url=os.environ[f"HR_TEST_{prefix}_AMQP_URL"],
        )
        engine = make_engine(config.database_url.get_secret_value())
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        finally:
            engine.dispose()
        connection, _ = connect(config)
        connection.close()
except Exception:
    raise SystemExit(
        "Integration dependencies unavailable: start the disposable PostgreSQL/RabbitMQ stack"
    ) from None
os.environ["HR_TEST_ENABLE_HTTP"] = "1"
raise SystemExit(pytest.main(["-q", "--tb=short"]))
