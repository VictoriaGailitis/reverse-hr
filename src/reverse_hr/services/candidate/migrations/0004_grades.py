"""Candidate-owned minimal human decision projection."""

import sqlalchemy as sa
from alembic import op

revision = "0004_candidate"
down_revision = "0003_candidate"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_grade_history",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("summary", sa.JSON(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_candidate_grade_history_candidate_id", "candidate_grade_history", ["candidate_id"]
    )


def downgrade():
    for table in ("candidate_grade_history", "candidate_profiles"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Candidate grade projection")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM candidate_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade populated Candidate deletion tombstones")
    op.drop_table("candidate_grade_history")
