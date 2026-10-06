"""Pinned plans, preflight sessions and deletion restrictions."""

import sqlalchemy as sa
from alembic import op

revision = "0003_assessment"
down_revision = "0002_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "plan_versions",
        sa.Column("plan_version_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("specialization", sa.String(100), nullable=False),
        sa.Column("grade", sa.String(16), nullable=False),
        sa.Column("revision_ids", sa.JSON(), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_reason", sa.String(2000), nullable=False),
        sa.Column("retired_by", sa.String(36)),
        sa.Column("retirement_reason", sa.String(2000)),
    )
    op.create_table(
        "assessment_sessions",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column(
            "plan_version_id",
            sa.String(36),
            sa.ForeignKey("plan_versions.plan_version_id"),
            nullable=False,
        ),
        sa.Column("consent_id", sa.String(36), nullable=False),
        sa.Column("stages", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_assessment_sessions_candidate_id", "assessment_sessions", ["candidate_id"])
    op.create_table(
        "assessment_subjects",
        sa.Column("subject", sa.String(36), primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("request_id", sa.String(36), unique=True),
        sa.Column("status", sa.String(16)),
    )


def downgrade():
    connection = op.get_bind()
    for table in ("plan_versions", "assessment_sessions"):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated assessment plans/sessions")
    if connection.execute(
        sa.text("SELECT 1 FROM assessment_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated assessment restrictions")
    op.drop_table("assessment_subjects")
    op.drop_table("assessment_sessions")
    op.drop_table("plan_versions")
