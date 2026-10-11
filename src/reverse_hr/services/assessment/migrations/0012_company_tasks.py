"""Private review/proposal state with data-preserving rollback guard."""

import sqlalchemy as sa
from alembic import op

revision = "0012_assessment"
down_revision = "0011_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_task_proposals",
        sa.Column("proposal_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(36), nullable=False, primary_key=False),
        sa.Column("name", sa.String(200), nullable=False, primary_key=False),
        sa.Column("content", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("reviewed_by", sa.String(36), nullable=True, primary_key=False),
        sa.Column("review_reason", sa.String(2000), nullable=True, primary_key=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("revision_id", sa.String(36), nullable=True, primary_key=False),
        sa.UniqueConstraint("revision_id"),
    )
    op.create_index(
        "ix_company_task_proposals_created_by", "company_task_proposals", ["created_by"]
    )
    op.create_index(
        "ix_company_task_proposals_organization_id", "company_task_proposals", ["organization_id"]
    )
    op.create_index(
        "ix_company_task_proposals_reviewed_by", "company_task_proposals", ["reviewed_by"]
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_task_proposals LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated company proposal data")
    bind = op.get_bind()
    for table in (
        "grade_policies",
        "grade_decisions",
        "candidate_grades",
        "suite_validation_intakes",
        "test_suites",
        "assessment_stages",
        "assessment_sessions",
        "plan_versions",
        "content_revisions",
        "stage_nonces",
        "material_nonces",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Cannot downgrade populated assessment content"
                if table == "content_revisions"
                else "Cannot downgrade populated assessment lifecycle or test suites"
            )
    if bind.execute(
        sa.text("SELECT 1 FROM assessment_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard assessment restrictions")
    op.drop_table("company_task_proposals")
