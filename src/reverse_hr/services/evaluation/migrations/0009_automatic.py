"""Distinguish machine proposals from human stage reviews."""

import sqlalchemy as sa
from alembic import op

revision = "0009_evaluation"
down_revision = "0008_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "evaluation_reviews",
        sa.Column("origin", sa.String(16), nullable=False, server_default="human"),
    )
    op.create_table(
        "evaluation_automatic_reviews",
        sa.Column("stage_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reason", sa.String(100), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    # Check older lifecycle guards before SQLite performs non-transactional DDL.
    for table in (
        "evaluation_model_attempts",
        "evaluation_test_evidence",
        "evaluation_result_nonces",
        "evaluation_reviews",
        "evaluation_intakes",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Evaluation evidence or reviews")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM evaluation_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade populated Evaluation intake or tombstones")
    if op.get_bind().execute(sa.text("SELECT 1 FROM evaluation_automatic_reviews LIMIT 1")).first():
        raise RuntimeError("Cannot discard automatic review history")
    op.drop_table("evaluation_automatic_reviews")
    op.drop_column("evaluation_reviews", "origin")
