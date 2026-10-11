"""Immutable private demo test-suite catalogue (no runtime validation)."""

import sqlalchemy as sa
from alembic import op

revision = "0007_assessment"
down_revision = "0006_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "test_suites",
        sa.Column("suite_id", sa.String(36), primary_key=True),
        sa.Column(
            "revision_id",
            sa.String(36),
            sa.ForeignKey("content_revisions.revision_id"),
            nullable=False,
        ),
        sa.Column("task_key", sa.String(64), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("definition", sa.JSON(), nullable=False),
        sa.Column("definition_digest", sa.String(64), nullable=False),
        sa.Column("content_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reviewed_by", sa.String(36)),
        sa.Column("review_reason", sa.String(2000)),
        sa.Column("retired_by", sa.String(36)),
        sa.Column("retirement_reason", sa.String(2000)),
        sa.UniqueConstraint("revision_id", "task_key", "number"),
    )


def downgrade():
    connection = op.get_bind()
    for table in (
        "test_suites",
        "assessment_stages",
        "assessment_sessions",
        "plan_versions",
        "content_revisions",
        "stage_nonces",
        "material_nonces",
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Cannot downgrade populated assessment content"
                if table == "content_revisions"
                else "Cannot downgrade populated assessment lifecycle or test suites"
            )
    if connection.execute(
        sa.text("SELECT 1 FROM assessment_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard assessment restrictions")
    op.drop_table("test_suites")
