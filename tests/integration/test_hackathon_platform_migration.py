from uuid import NAMESPACE_URL, uuid4, uuid5

from alembic import command
from sqlalchemy import select
from sqlalchemy.orm import Session

from reverse_hr.platform.migrate import migration_config
from reverse_hr.services.achievements.domain.achievements import SourceRow
from reverse_hr.services.demo_sources.domain.demo_sources import external_record_id
from scripts.upgrade_hackathon_platform import upgrade


def test_adapter_rename_preserves_custom_name_and_source_identity(service):
    target = service("achievements")
    config = migration_config(target.app.state.settings)
    command.downgrade(config, "0002_achievements")
    with Session(target.app.state.engine) as session, session.begin():
        source = session.scalar(select(SourceRow).where(SourceRow.adapter == "demo-codenrock"))
        identity = source.source_id
        source.name = "Our configured hackathon provider"
    command.upgrade(config, "head")
    with Session(target.app.state.engine) as session:
        source = session.get(SourceRow, identity)
        assert source.adapter == "demo-hackathon-platform"
        assert source.key == "demo-hackathon-platform"
        assert source.name == "Our configured hackathon provider"
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert target.client.get("/health/ready").status_code == 200


def test_external_ids_stay_stable_after_adapter_rename():
    candidate = uuid4()
    previous = str(uuid5(NAMESPACE_URL, "demo-codenrock:" + str(candidate)))
    assert external_record_id("demo-hackathon-platform", candidate) == previous


def test_existing_config_upgrade_is_idempotent_and_retains_signing_key(tmp_path):
    env = tmp_path / ".env"
    env.write_text("DEMO_CODENROCK_DB_PASSWORD=example-secret\nOTHER_SETTING=kept\n")
    secrets = tmp_path / ".secrets"
    secrets.mkdir()
    old = secrets / "demo-codenrock.key"
    old.write_bytes(b"demo-key")
    upgrade(tmp_path)
    first = env.read_text()
    upgrade(tmp_path)
    assert env.read_text() == first
    assert "OTHER_SETTING=kept" in first
    assert "DEMO_HACKATHON_PLATFORM_DB_PASSWORD=example-secret" in first
    assert "@postgres:5432/demo_codenrock" in first
    assert (secrets / "demo-hackathon-platform.key").read_bytes() == old.read_bytes()
