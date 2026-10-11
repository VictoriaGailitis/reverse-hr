"""Immutable assessment content and publication decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_assessment"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "content_families",
        sa.Column("family_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("specialization", sa.String(100), nullable=False),
        sa.Column("grade", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "content_revisions",
        sa.Column("revision_id", sa.String(36), primary_key=True),
        sa.Column(
            "family_id", sa.String(36), sa.ForeignKey("content_families.family_id"), nullable=False
        ),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("review_reason", sa.String(2000)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("retired_by", sa.String(36)),
        sa.Column("retirement_reason", sa.String(2000)),
        sa.Column("retired_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("family_id", "number"),
    )
    op.create_index("ix_content_revisions_family_id", "content_revisions", ["family_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM content_revisions LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated assessment content history")
    op.drop_table("content_revisions")
    op.drop_table("content_families")
