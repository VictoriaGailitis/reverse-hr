"""Multiple active specializations, preserving the existing primary profile."""

import sqlalchemy as sa
from alembic import op

revision = "0008_candidate"
down_revision = "0007_candidate"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "candidate_profiles",
        sa.Column("additional_specializations", sa.JSON(), nullable=False, server_default="[]"),
    )


def downgrade():
    # Guard older protected state before SQLite's nontransactional DDL on a longer downgrade.
    for table in (
        "candidate_profiles",
        "candidate_grade_history",
        "candidate_preferences",
        "candidate_contacts",
        "candidate_publication",
        "candidate_market_nonces",
        "candidate_resume_imports",
        "candidate_resumes",
        "candidate_resume_store",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated resume or specialization state")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM candidate_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade deletion tombstones")
    op.drop_column("candidate_profiles", "additional_specializations")
