"""Replay protection for Evaluation artifact export."""

import sqlalchemy as sa
from alembic import op

revision = "0005_workspace"
down_revision = "0004_workspace"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "artifact_nonces",
        sa.Column("nonce", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    connection = op.get_bind()
    for table in (
        "workspaces",
        "workspace_runs",
        "workspace_snapshots",
        "runner_nonces",
        "snapshot_nonces",
        "artifact_nonces",
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Cannot downgrade populated workspaces or artifact replay protection"
            )
    if connection.execute(
        sa.text("SELECT 1 FROM workspace_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard workspace restrictions")
    op.drop_table("artifact_nonces")
