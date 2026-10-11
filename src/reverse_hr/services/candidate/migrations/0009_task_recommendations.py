"""Opt-in task discovery and deduplicated notices."""

import sqlalchemy as sa
from alembic import op

revision = "0009_candidate"
down_revision = "0008_candidate"
branch_labels = depends_on = None


def upgrade():
    op.create_table(
        "candidate_task_subscriptions",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("consent_id", sa.String(36)),
        sa.Column("stack_tags", sa.JSON(), nullable=False),
        sa.Column("interval_hours", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("catalog_after", sa.String(36)),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_sent_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "candidate_task_recommendations",
        sa.Column("notice_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False, index=True),
        sa.Column("version_id", sa.String(36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("candidate_id", "version_id"),
    )


def downgrade():
    # Preflight older protected migrations before nontransactional SQLite DDL.
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
        raise RuntimeError("Cannot discard deletion tombstones")
    for table in ("candidate_task_subscriptions", "candidate_task_recommendations"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot discard task subscriptions or notice history")
    op.drop_table("candidate_task_recommendations")
    op.drop_table("candidate_task_subscriptions")
