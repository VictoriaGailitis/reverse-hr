"""Immutable preparation snapshots, run intents and permanent restrictions."""

import sqlalchemy as sa
from alembic import op

revision = "0002_workspace"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "workspaces",
        sa.Column("workspace_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("stage_id", sa.String(36), nullable=False),
        sa.Column("format", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.UniqueConstraint("candidate_id", "session_id", "stage_id"),
    )
    op.create_index("ix_workspaces_candidate_id", "workspaces", ["candidate_id"])
    op.create_table(
        "workspace_snapshots",
        sa.Column("snapshot_id", sa.String(36), primary_key=True),
        sa.Column(
            "workspace_id", sa.String(36), sa.ForeignKey("workspaces.workspace_id"), nullable=False
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("files", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("workspace_id", "version"),
    )
    op.create_table(
        "workspace_runs",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column(
            "snapshot_id",
            sa.String(36),
            sa.ForeignKey("workspace_snapshots.snapshot_id"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "workspace_subjects",
        sa.Column("subject", sa.String(36), primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("request_id", sa.String(36), unique=True),
    )


def downgrade():
    for table in ("workspaces", "workspace_snapshots", "workspace_runs"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated workspaces")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM workspace_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot discard workspace restrictions")
    for table in ("workspace_subjects", "workspace_runs", "workspace_snapshots", "workspaces"):
        op.drop_table(table)
