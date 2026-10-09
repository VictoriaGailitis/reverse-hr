"""Frozen trust, review and appeals storage."""

import sqlalchemy as sa
from alembic import context, op

revision = "0007_hiring"
down_revision = "0006_hiring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_employer_reviews",
        sa.Column("review_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("invitation_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("author_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("invitation_id"),
    )
    op.create_index(
        "ix_hiring_employer_reviews_author_id", "hiring_employer_reviews", ["author_id"]
    )
    op.create_index(
        "ix_hiring_employer_reviews_invitation_id", "hiring_employer_reviews", ["invitation_id"]
    )
    op.create_index(
        "ix_hiring_employer_reviews_organization_id", "hiring_employer_reviews", ["organization_id"]
    )
    op.create_index(
        "ix_hiring_employer_reviews_reviewer_id", "hiring_employer_reviews", ["reviewer_id"]
    )
    op.create_table(
        "hiring_moderation_appeals",
        sa.Column("appeal_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("target_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("target_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(16), nullable=False, primary_key=False),
        sa.Column("author_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("target_id", "target_version", "author_id"),
    )
    op.create_index(
        "ix_hiring_moderation_appeals_author_id", "hiring_moderation_appeals", ["author_id"]
    )
    op.create_index(
        "ix_hiring_moderation_appeals_reviewer_id", "hiring_moderation_appeals", ["reviewer_id"]
    )
    op.create_index(
        "ix_hiring_moderation_appeals_target_id", "hiring_moderation_appeals", ["target_id"]
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM hiring_employer_reviews LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated trust history")
    if bind.execute(sa.text("SELECT 1 FROM hiring_moderation_appeals LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated trust history")
    if context.get_revision_argument() != "0006_hiring":
        target = context.get_revision_argument()
        tables = ["hiring_ats_statuses"]
        if target != "0005_hiring":
            tables += [
                "hiring_vacancies",
                "hiring_vacancy_decisions",
                "hiring_applications",
                "hiring_application_changes",
            ]
        if target not in {"0005_hiring", "0004_hiring"}:
            tables += ["hiring_complaint_cases", "hiring_complaint_decisions"]
        if target not in {"0005_hiring", "0004_hiring", "0003_hiring"}:
            tables += [
                "hiring_dialogs",
                "hiring_messages",
                "hiring_employer_blocks",
                "hiring_complaints",
                "hiring_notices",
            ]
        if target not in {"0005_hiring", "0004_hiring", "0003_hiring", "0002_hiring"}:
            tables += ["hiring_needs", "hiring_invitations", "hiring_market_nonces"]
            if bind.execute(
                sa.text("SELECT 1 FROM hiring_subjects WHERE blocked = true LIMIT 1")
            ).first():
                raise RuntimeError("Cannot downgrade deletion tombstones")
        # Check the entire requested path before the first DDL, including SQLite.
        for table in tables:
            if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
                raise RuntimeError("Cannot downgrade populated Hiring data")
    op.drop_table("hiring_moderation_appeals")
    op.drop_table("hiring_employer_reviews")
