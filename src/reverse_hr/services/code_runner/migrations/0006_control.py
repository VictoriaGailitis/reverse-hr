"""Serialize diagnostic/execution queue ownership across differently configured workers."""

import sqlalchemy as sa
from alembic import op

revision = "0006_control"
down_revision = "0005_cancellation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runner_control",
        sa.Column("control_id", sa.Integer(), primary_key=True),
        sa.Column("mode", sa.String(16)),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.execute("INSERT INTO runner_control (control_id, mode, version) VALUES (1, NULL, 1)")


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
    op.drop_table("runner_control")
