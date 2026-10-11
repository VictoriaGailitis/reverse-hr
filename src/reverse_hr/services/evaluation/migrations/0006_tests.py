"""Signed hidden-test evidence and transport replay protection."""

import sqlalchemy as sa
from alembic import op

revision = "0006_evaluation"
down_revision = "0005_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_test_evidence",
        sa.Column("stage_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("proof", sa.JSON(), nullable=False),
        sa.Column("signature", sa.String(128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_evaluation_test_evidence_candidate_id", "evaluation_test_evidence", ["candidate_id"]
    )
    op.create_table(
        "evaluation_result_nonces",
        sa.Column("nonce", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    bind = op.get_bind()
    for table in (
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
        raise RuntimeError("Cannot discard Evaluation restrictions")
    op.drop_table("evaluation_result_nonces")
    op.drop_table("evaluation_test_evidence")
