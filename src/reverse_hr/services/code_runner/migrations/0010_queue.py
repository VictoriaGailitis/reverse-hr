"""Durable own-node validation work and immutable delivery material."""

import sqlalchemy as sa
from alembic import op

revision = "0010_queue"
down_revision = "0009_verdicts"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "validation_work",
        sa.Column(
            "validation_id",
            sa.String(36),
            sa.ForeignKey("validation_batches.validation_id"),
            primary_key=True,
        ),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("node_id", sa.String(36), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error_code", sa.String(32)),
        sa.Column("attestation", sa.JSON()),
        sa.Column("attestation_signature", sa.String(128)),
        sa.Column("receipt", sa.JSON()),
    )
    for column in ("owner_id", "node_id", "next_run_at"):
        op.create_index(f"ix_validation_work_{column}", "validation_work", [column])


def downgrade():
    connection = op.get_bind()
    for table, message in (
        ("validation_work", "Cannot discard validation work"),
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
    op.drop_table("validation_work")
