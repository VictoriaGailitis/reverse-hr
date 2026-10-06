"""Durable cleanup obligations and delayed privacy ACK."""

import sqlalchemy as sa
from alembic import op

revision = "0003_attempts"
down_revision = "0002_runner"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("runner_subjects", sa.Column("deletion_status", sa.String(16)))
    op.add_column("runner_subjects", sa.Column("deletion_correlation_id", sa.String(36)))
    op.execute("UPDATE runner_subjects SET deletion_status = 'deleted' WHERE blocked = true")
    op.create_table(
        "runner_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        sa.Column("run_id", sa.String(36), nullable=False, unique=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_runner_attempts_candidate_id", "runner_attempts", ["candidate_id"])
    op.create_index("ix_runner_attempts_node_id", "runner_attempts", ["node_id"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM runner_attempts LIMIT 1")).first():
        raise RuntimeError("Cannot discard execution cleanup obligations")
    if connection.execute(
        sa.text("SELECT 1 FROM runner_subjects WHERE deletion_status = 'restricted' LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard pending cleanup restrictions")
    if connection.execute(sa.text("SELECT 1 FROM runner_jobs LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated runner jobs")
    if connection.execute(
        sa.text("SELECT 1 FROM runner_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard runner restrictions")
    op.drop_table("runner_attempts")
    with op.batch_alter_table("runner_subjects") as batch:
        batch.drop_column("deletion_correlation_id")
        batch.drop_column("deletion_status")
