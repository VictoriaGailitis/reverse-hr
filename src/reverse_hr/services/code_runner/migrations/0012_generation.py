"""Durable generated suite validation intents."""

import sqlalchemy as sa
from alembic import op

revision = "0012_generation"
down_revision = "0011_submitted"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "runner_generated_validations",
        sa.Column("generation_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False, index=True),
        sa.Column("validation_id", sa.String(36)),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    # Check older lifecycle guards before SQLite performs non-transactional DDL.
    bind = op.get_bind()
    for table in (
        "submitted_jobs",
        "submitted_attempts",
        "validation_work",
        "validation_verdicts",
        "validation_captures",
        "validation_attempts",
        "validation_batches",
        "runner_results",
        "runner_attempts",
        "runner_jobs",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                {
                    "runner_jobs": "Cannot downgrade populated runner jobs",
                    "runner_results": "Cannot discard private execution results",
                    "validation_captures": "Cannot discard private validation captures",
                    "validation_verdicts": "Cannot discard signed validation verdicts",
                }.get(table, "Cannot discard runner work or cleanup obligations")
            )
    if bind.execute(sa.text("SELECT 1 FROM runner_subjects WHERE blocked = true LIMIT 1")).first():
        raise RuntimeError("Cannot discard runner restrictions")
    if op.get_bind().execute(sa.text("SELECT 1 FROM runner_generated_validations LIMIT 1")).first():
        raise RuntimeError("Cannot discard generated validation history")
    op.drop_table("runner_generated_validations")
