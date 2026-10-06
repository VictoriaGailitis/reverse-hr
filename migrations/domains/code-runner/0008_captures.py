"""Private host captures after confirmed validation sandbox cleanup."""

import sqlalchemy as sa
from alembic import op

revision = "0008_captures"
down_revision = "0007_validation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "validation_captures",
        sa.Column(
            "attempt_id",
            sa.String(36),
            sa.ForeignKey("validation_attempts.attempt_id"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("capture", sa.JSON(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_validation_captures_owner_id", "validation_captures", ["owner_id"])


def downgrade():
    connection = op.get_bind()
    for table, message in (
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
    op.drop_table("validation_captures")
