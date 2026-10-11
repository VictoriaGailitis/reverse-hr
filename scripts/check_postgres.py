"""Check the project's local PostgreSQL roles without printing credentials."""

import argparse

import psycopg
from alembic import command
from dotenv import dotenv_values

from reverse_hr.platform.migrate import migration_config
from reverse_hr.platform.settings import Settings

parser = argparse.ArgumentParser()
parser.add_argument("--port", type=int, default=55329)
args = parser.parse_args()
secrets = dotenv_values(".env")

for service in ("candidate", "privacy", "employer"):
    password = secrets[f"{service.upper()}_DB_PASSWORD"]
    url = f"postgresql+psycopg://{service}:{password}@localhost:{args.port}/{service}"
    settings = Settings(service_name=service, database_url=url)
    command.upgrade(migration_config(settings), "head")
    with psycopg.connect(
        host="localhost", port=args.port, user=service, password=password, dbname=service
    ) as connection:
        tables = connection.execute(
            "SELECT tablename FROM pg_tables WHERE schemaname='public'"
        ).fetchall()
        own = {
            "candidate": "candidate_profiles",
            "privacy": "consents",
            "employer": "organizations",
        }[service]
        assert own in {row[0] for row in tables}
    foreign = "employer" if service != "employer" else "candidate"
    try:
        connection = psycopg.connect(
            host="localhost", port=args.port, user=service, password=password, dbname=foreign
        )
    except psycopg.OperationalError:
        pass
    else:
        connection.close()
        raise AssertionError(f"{service} unexpectedly connected to {foreign}")
    print(f"{service}: migration applied, foreign database access denied")
