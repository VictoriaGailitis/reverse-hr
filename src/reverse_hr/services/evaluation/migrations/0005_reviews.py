"""Human demo review revisions and nullable stage scores."""

import sqlalchemy as sa
from alembic import op

revision = "0005_evaluation"
down_revision = "0004_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluation_intakes", sa.Column("score", sa.Integer()))
    op.add_column(
        "evaluation_intakes",
        sa.Column("review_number", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "evaluation_reviews",
        sa.Column("review_id", sa.String(36), primary_key=True),
        sa.Column(
            "stage_id", sa.String(36), sa.ForeignKey("evaluation_intakes.stage_id"), nullable=False
        ),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("intake_version", sa.Integer(), nullable=False),
        sa.Column("decisions", sa.JSON(), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stage_id", "number"),
    )
    for name in ("stage_id", "candidate_id", "reviewer_id"):
        op.create_index(f"ix_evaluation_reviews_{name}", "evaluation_reviews", [name])


def downgrade():
    bind = op.get_bind()
    for table in ("evaluation_reviews", "evaluation_intakes"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Evaluation intake or reviews")
    if bind.execute(
        sa.text("SELECT 1 FROM evaluation_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated Evaluation intake or tombstones")
    op.drop_table("evaluation_reviews")
    with op.batch_alter_table("evaluation_intakes") as batch:
        batch.drop_column("score")
        batch.drop_column("review_number")
