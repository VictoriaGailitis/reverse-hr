"""Candidate-confirmed employment preferences and contact correction CAS version."""

import sqlalchemy as sa
from alembic import op

revision = "0007_candidate"
down_revision = "0006_candidate"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "candidate_contacts", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "candidate_preferences",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("share_in_matching", sa.Boolean(), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM candidate_preferences LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated preference state")
    # Protect longer downgrade paths before any DDL, including preexisting resume state.
    for table in (
        "candidate_resume_imports",
        "candidate_resumes",
        "candidate_resume_store",
        "candidate_profiles",
        "candidate_contacts",
        "candidate_publication",
        "candidate_market_nonces",
        "candidate_grade_history",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated resume state")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM candidate_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade deletion tombstones")
    op.drop_table("candidate_preferences")
    op.drop_column("candidate_contacts", "version")
