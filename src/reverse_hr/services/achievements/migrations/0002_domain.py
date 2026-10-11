"""Frozen schema for source-scoped achievements and demo exchanges."""

import sqlalchemy as sa
from alembic import op

revision = "0002_achievements"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "achievement_connections",
        sa.Column("connection_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("source_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("external_account", sa.String(length=128), nullable=True, primary_key=False),
        sa.Column("consent_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("last_sync_status", sa.String(length=24), nullable=True, primary_key=False),
        sa.UniqueConstraint("source_id", "external_account"),
        sa.UniqueConstraint("candidate_id", "source_id"),
    )
    op.create_index(
        "ix_achievement_connections_candidate_id",
        "achievement_connections",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        "ix_achievement_connections_source_id",
        "achievement_connections",
        ["source_id"],
        unique=False,
    )
    op.create_table(
        "achievement_history",
        sa.Column("history_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("achievement_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("action", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("reason", sa.String(length=2000), nullable=True, primary_key=False),
        sa.Column("snapshot", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_achievement_history_candidate_id", "achievement_history", ["candidate_id"], unique=False
    )
    op.create_index(
        "ix_achievement_history_actor_id", "achievement_history", ["actor_id"], unique=False
    )
    op.create_index(
        "ix_achievement_history_achievement_id",
        "achievement_history",
        ["achievement_id"],
        unique=False,
    )
    op.create_table(
        "achievement_imports",
        sa.Column("import_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("source_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("records", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("results", sa.JSON(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_achievement_imports_created_by", "achievement_imports", ["created_by"], unique=False
    )
    op.create_index(
        "ix_achievement_imports_source_id", "achievement_imports", ["source_id"], unique=False
    )
    op.create_table(
        "achievement_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "achievement_sources",
        sa.Column("source_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("key", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("adapter", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("name", sa.String(length=100), nullable=False, primary_key=False),
        sa.Column("partner_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("key"),
        sa.UniqueConstraint("partner_id"),
    )
    op.create_table(
        "achievement_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.UniqueConstraint("request_id"),
    )
    op.create_table(
        "achievements",
        sa.Column("achievement_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("source_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("external_id", sa.String(length=128), nullable=False, primary_key=False),
        sa.Column("connection_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("external_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("demo", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("published", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("publication_consent_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("source_id", "external_id"),
    )
    op.create_index(
        "ix_achievements_connection_id", "achievements", ["connection_id"], unique=False
    )
    op.create_index("ix_achievements_candidate_id", "achievements", ["candidate_id"], unique=False)
    op.create_index("ix_achievements_source_id", "achievements", ["source_id"], unique=False)
    op.bulk_insert(
        sa.table(
            "achievement_sources",
            sa.column("source_id"),
            sa.column("key"),
            sa.column("adapter"),
            sa.column("name"),
            sa.column("partner_id"),
            sa.column("enabled"),
            sa.column("version"),
        ),
        [
            {
                "source_id": "452fe03c-396c-5895-a8c5-f4700033b7b8",
                "key": "demo-fsp",
                "adapter": "demo-fsp",
                "name": "Synthetic demo-fsp",
                "partner_id": None,
                "enabled": True,
                "version": 1,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "achievement_sources",
            sa.column("source_id"),
            sa.column("key"),
            sa.column("adapter"),
            sa.column("name"),
            sa.column("partner_id"),
            sa.column("enabled"),
            sa.column("version"),
        ),
        [
            {
                "source_id": "75659214-aac8-56e6-9fa7-122bafbf719c",
                "key": "demo-codenrock",
                "adapter": "demo-codenrock",
                "name": "Synthetic demo-codenrock",
                "partner_id": None,
                "enabled": True,
                "version": 1,
            }
        ],
    )
    op.bulk_insert(
        sa.table(
            "achievement_sources",
            sa.column("source_id"),
            sa.column("key"),
            sa.column("adapter"),
            sa.column("name"),
            sa.column("partner_id"),
            sa.column("enabled"),
            sa.column("version"),
        ),
        [
            {
                "source_id": "af696878-c36d-55b2-b236-68e9239cf734",
                "key": "self",
                "adapter": "self",
                "name": "Self-declared",
                "partner_id": None,
                "enabled": True,
                "version": 1,
            }
        ],
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM achievement_connections LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated achievements data")
    if bind.execute(sa.text("SELECT 1 FROM achievement_history LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated achievements data")
    if bind.execute(sa.text("SELECT 1 FROM achievement_imports LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated achievements data")
    if bind.execute(sa.text("SELECT 1 FROM achievement_nonces LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated achievements data")
    if bind.execute(
        sa.text(
            "SELECT 1 FROM achievement_sources "
            "WHERE key NOT IN ('demo-fsp','demo-codenrock','self') LIMIT 1"
        )
    ).first():
        raise RuntimeError("Cannot downgrade populated achievements data")
    if bind.execute(
        sa.text("SELECT 1 FROM achievement_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated achievements data")
    if bind.execute(sa.text("SELECT 1 FROM achievements LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated achievements data")
    op.drop_table("achievements")
    op.drop_table("achievement_subjects")
    op.drop_table("achievement_sources")
    op.drop_table("achievement_nonces")
    op.drop_table("achievement_imports")
    op.drop_table("achievement_history")
    op.drop_table("achievement_connections")
