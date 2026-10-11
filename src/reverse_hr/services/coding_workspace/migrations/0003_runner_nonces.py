"""Replay protection for run manifest retrieval."""

import sqlalchemy as sa
from alembic import op

revision = "0003_workspace"
down_revision = "0002_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "workspace_runs",
        sa.Column("runner_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "workspace_runs",
        sa.Column("status", sa.String(24), nullable=False, server_default="pending_runner"),
    )
    op.create_table(
        "runner_nonces",
        sa.Column("nonce", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for table in ("workspaces", "workspace_runs", "workspace_snapshots"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated workspaces")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM workspace_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot discard workspace restrictions")
    if op.get_bind().execute(sa.text("SELECT 1 FROM runner_nonces LIMIT 1")).first():
        raise RuntimeError("Cannot discard active manifest replay protection")
    op.drop_table("runner_nonces")
    op.drop_column("workspace_runs", "status")
    op.drop_column("workspace_runs", "runner_version")
