"""Durable run intake, diagnostics and deletion restrictions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_runner"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runner_jobs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("error_code", sa.String(32)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("correlation_id", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runner_jobs_candidate_id", "runner_jobs", ["candidate_id"])
    op.create_table(
        "runner_subjects",
        sa.Column("subject", sa.String(36), primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("request_id", sa.String(36), unique=True),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM runner_jobs LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated runner jobs")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM runner_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot discard runner restrictions")
    op.drop_table("runner_subjects")
    op.drop_table("runner_jobs")
