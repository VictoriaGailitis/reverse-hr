"""Immutable signed full-matrix demo suite verdicts."""

import sqlalchemy as sa
from alembic import op

revision = "0009_verdicts"
down_revision = "0008_captures"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "validation_verdicts",
        sa.Column(
            "validation_id",
            sa.String(36),
            sa.ForeignKey("validation_batches.validation_id"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("proof", sa.JSON(), nullable=False),
        sa.Column("signature", sa.String(128), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_validation_verdicts_owner_id", "validation_verdicts", ["owner_id"])


def downgrade():
    connection = op.get_bind()
    for table, message in (
        ("validation_verdicts", "Cannot discard signed validation verdicts"),
        ("validation_captures", "Cannot discard private validation captures"),
        ("validation_attempts", "Cannot discard validation cleanup obligations"),
        ("validation_batches", "Cannot discard validation batches"),
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
    op.drop_table("validation_verdicts")
