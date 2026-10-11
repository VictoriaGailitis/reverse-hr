"""Latest grading migrations preserve existing data before any DDL rollback."""

import pytest
from alembic import command
from sqlalchemy.orm import Session

from reverse_hr.platform.migrate import migration_config
from reverse_hr.services.code_runner.domain.code_runner import process_deletion_request
from tests.services.code_runner.test_code_runner import deletion


@pytest.mark.parametrize("name", ["assessment", "evaluation", "code-runner"])
def test_empty_grading_migrations_roundtrip(service, name):
    target = service(name)
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200


def test_runner_tombstone_prevents_partial_grading_downgrade(service):
    from uuid import uuid4

    target = service("code-runner")
    with Session(target.app.state.engine) as session, session.begin():
        process_deletion_request(session, deletion(uuid4()))
    with pytest.raises(RuntimeError):
        command.downgrade(migration_config(target.app.state.settings), "base")
    assert target.client.get("/health/ready").status_code == 200
