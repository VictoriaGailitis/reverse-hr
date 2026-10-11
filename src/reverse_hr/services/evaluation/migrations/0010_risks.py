"""Persistent suspicion signals and independent verification decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0010_evaluation"
down_revision = "0009_evaluation"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "evaluation_risks",
        sa.Column("stage_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False, index=True),
        sa.Column("source_digest", sa.String(64), nullable=False),
        sa.Column("codes", sa.JSON(), nullable=False),
        sa.Column("rule_version", sa.String(40), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewer_id", sa.String(36)),
        sa.Column("reason", sa.String(2000)),
        sa.Column("verification_stage_id", sa.String(36)),
    )


def downgrade():
    # Preflight older protected migrations before nontransactional SQLite DDL.
    for table in (
        "evaluation_intakes",
        "evaluation_reviews",
        "evaluation_model_attempts",
        "evaluation_test_evidence",
        "evaluation_result_nonces",
        "evaluation_automatic_reviews",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Evaluation evidence or reviews")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM evaluation_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot discard deletion tombstones")
    if op.get_bind().execute(sa.text("SELECT 1 FROM evaluation_risks LIMIT 1")).first():
        raise RuntimeError("Cannot discard risk history")
    op.drop_table("evaluation_risks")
