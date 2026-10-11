"""Service-owned recruitment state; protect data before downgrade DDL."""

import sqlalchemy as sa
from alembic import op

revision = "0002_matching"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "matching_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, unique=True),
    )
    op.create_table(
        "matching_candidates",
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("card", sa.JSON(), nullable=True),
    )
    op.create_table(
        "matching_snapshots",
        sa.Column("snapshot_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("requested_by", sa.String(length=36), nullable=False),
        sa.Column("need_author", sa.String(length=36), nullable=False),
        sa.Column("query", sa.JSON(), nullable=False),
        sa.Column("need_digest", sa.String(length=64), nullable=False),
        sa.Column("matches", sa.JSON(), nullable=False),
        sa.Column("next_cursor", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_matching_snapshots_need_author", "matching_snapshots", ["need_author"])
    op.create_index("ix_matching_snapshots_requested_by", "matching_snapshots", ["requested_by"])


def downgrade():
    for table in ("matching_candidates", "matching_snapshots"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated recruitment data")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM matching_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade deletion tombstones")
    op.drop_table("matching_snapshots")
    op.drop_table("matching_candidates")
    op.drop_table("matching_subjects")
