"""Private PDF imports and candidate-confirmed resume declarations."""

import sqlalchemy as sa
from alembic import op

revision = "0006_candidate"
down_revision = "0005_candidate"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_resume_imports",
        sa.Column("import_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("size", sa.Integer(), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("error", sa.String(32)),
        sa.Column("extraction", sa.JSON()),
        sa.Column("proposal", sa.JSON()),
        sa.UniqueConstraint("candidate_id", "digest"),
    )
    op.create_index(
        "ix_candidate_resume_imports_candidate_id", "candidate_resume_imports", ["candidate_id"]
    )
    op.create_table(
        "candidate_resumes",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("fields", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("consent_id", sa.String(36)),
    )
    op.create_table(
        "candidate_resume_store",
        sa.Column("name", sa.String(16), primary_key=True),
        sa.Column("identity", sa.String(36), nullable=False),
    )


def downgrade():
    # The profile/contacts may already contain declarations confirmed from an import.
    # Refuse before any DDL, including when a longer downgrade would erase tombstones.
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
    op.drop_table("candidate_resume_store")
    op.drop_table("candidate_resumes")
    op.drop_index("ix_candidate_resume_imports_candidate_id", table_name="candidate_resume_imports")
    op.drop_table("candidate_resume_imports")
