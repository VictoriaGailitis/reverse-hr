"""Explicit operator queue-mode change; never automatically switch active deployments."""

import argparse

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.platform.settings import Settings
from reverse_hr.services.code_runner.domain.code_runner import ExecutionAttempt, RunnerControl
from reverse_hr.shared.db import make_engine


def set_mode(engine, mode, expected_version):
    if mode not in {"diagnostic", "execution"}:
        raise ValueError("Unknown runner mode")
    with Session(engine) as session, session.begin():
        row = session.scalar(
            select(RunnerControl)
            .where(RunnerControl.control_id == 1)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise HTTPException(503)
        if row.version != expected_version:
            raise HTTPException(409)
        if session.scalar(
            select(ExecutionAttempt.attempt_id).where(ExecutionAttempt.state != "cleaned").limit(1)
        ):
            raise HTTPException(409)
        row.mode, row.version = mode, row.version + 1
        return row.version


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=["diagnostic", "execution"])
    parser.add_argument("--if-match-version", type=int, required=True)
    args = parser.parse_args()
    settings = Settings()
    if settings.service_name != "code-runner":
        parser.error("Queue mode belongs only to Code Runner")
    engine = make_engine(settings.database_url.get_secret_value())
    try:
        version = set_mode(engine, args.mode, args.if_match_version)
        print(f"runner_mode_updated version={version}")
    except Exception:
        parser.error("Runner mode unavailable, version mismatch or cleanup obligations remain")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
