"""Immutable approved matching governance and employer-confirmed parsed intents."""

import sqlalchemy as sa
from alembic import op

revision = "0003_matching"
down_revision = "0002_matching"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "matching_policy_nonces",
        sa.Column("nonce", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "matching_governance_versions",
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("author_id", sa.String(36), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=True),
        sa.Column("reason", sa.String(1000), nullable=True),
    )
    op.create_table(
        "matching_intent_previews",
        sa.Column("preview_id", sa.String(36), primary_key=True),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("need_id", sa.String(36), nullable=False),
        sa.Column("need_digest", sa.String(64), nullable=False),
        sa.Column("catalog_id", sa.String(36), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("expires_at", sa.String(40), nullable=False),
        sa.Column("confirmed", sa.Boolean(), nullable=False),
    )
    op.create_index(
        "ix_matching_intent_previews_actor_id", "matching_intent_previews", ["actor_id"]
    )


def downgrade():
    for table in (
        "matching_governance_versions",
        "matching_intent_previews",
        "matching_candidates",
        "matching_snapshots",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated recruitment data")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM matching_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade deletion tombstones")
    op.drop_table("matching_policy_nonces")
    op.drop_table("matching_intent_previews")
    op.drop_table("matching_governance_versions")
