"""Separate suite validation batches and durable cleanup obligations."""

import sqlalchemy as sa
from alembic import op

revision = "0007_validation"
down_revision = "0006_control"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "validation_batches",
        sa.Column("validation_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("plan", sa.JSON()),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_validation_batches_owner_id", "validation_batches", ["owner_id"])
    op.create_table(
        "validation_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        sa.Column(
            "validation_id",
            sa.String(36),
            sa.ForeignKey("validation_batches.validation_id"),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("validation_id", "ordinal"),
    )
    op.create_index("ix_validation_attempts_owner_id", "validation_attempts", ["owner_id"])
    op.create_index("ix_validation_attempts_node_id", "validation_attempts", ["node_id"])


def downgrade():
    connection = op.get_bind()
    for table, message in (
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
    op.drop_table("validation_attempts")
    op.drop_table("validation_batches")
