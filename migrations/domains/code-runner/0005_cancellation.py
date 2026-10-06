"""Durable cancellation intent independent of execution event version."""

import sqlalchemy as sa
from alembic import op

revision = "0005_cancellation"
down_revision = "0004_results"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "runner_jobs",
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    connection = op.get_bind()
    for table, message in (
        ("runner_results", "Cannot discard private execution results"),
        ("runner_attempts", "Cannot discard execution cleanup obligations"),
        ("runner_jobs", "Cannot downgrade populated runner jobs"),
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(message)
    if connection.execute(
        sa.text("SELECT 1 FROM runner_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard runner restrictions")
    with op.batch_alter_table("runner_jobs") as batch:
        batch.drop_column("cancel_requested")
