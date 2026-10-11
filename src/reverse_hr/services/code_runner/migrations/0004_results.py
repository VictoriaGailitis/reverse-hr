"""Private bounded execution results; no score or solution verdict."""

import sqlalchemy as sa
from alembic import op

revision = "0004_results"
down_revision = "0003_attempts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runner_results",
        sa.Column("run_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("attempt_id", sa.String(36), unique=True, nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stdout", sa.Text(), nullable=False),
        sa.Column("stderr", sa.Text(), nullable=False),
        sa.Column("exit_code", sa.Integer()),
        sa.Column("reason", sa.String(32)),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runner_results_candidate_id", "runner_results", ["candidate_id"])


def downgrade():
    connection = op.get_bind()
    # Reject before any DDL; older revisions also reject these retained data.
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
    op.drop_table("runner_results")
