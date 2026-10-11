"""Provider-neutral bounded model attempt ledger; remote inference disabled by default."""

import sqlalchemy as sa
from alembic import op

revision = "0007_evaluation"
down_revision = "0006_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluation_reviews", sa.Column("model_attempt_id", sa.String(36)))
    op.create_table(
        "evaluation_model_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        *[
            sa.Column(name, sa.String(36), nullable=False)
            for name in ("stage_id", "candidate_id", "requested_by")
        ],
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("prompt_digest", sa.String(64), nullable=False),
        sa.Column("input_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("output", sa.JSON()),
        *[
            sa.Column(name, sa.Integer())
            for name in ("duration_ms", "input_tokens", "output_tokens", "cost_microusd")
        ],
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stage_id", "number"),
    )
    for name in ("stage_id", "candidate_id", "requested_by"):
        op.create_index(f"ix_evaluation_model_attempts_{name}", "evaluation_model_attempts", [name])


def downgrade():
    bind = op.get_bind()
    for table in (
        "evaluation_model_attempts",
        "evaluation_test_evidence",
        "evaluation_result_nonces",
        "evaluation_reviews",
        "evaluation_intakes",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Evaluation evidence or reviews")
    if bind.execute(
        sa.text("SELECT 1 FROM evaluation_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated Evaluation intake or tombstones")
    op.drop_table("evaluation_model_attempts")
    op.drop_column("evaluation_reviews", "model_attempt_id")
