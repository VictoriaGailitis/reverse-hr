"""Assignments bind a company recipient to a pinned assessment plan and session."""

import sqlalchemy as sa
from alembic import op

revision = "0013_assessment"
down_revision = "0012_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_assignments",
        sa.Column("assignment_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("proposal_id", sa.String(36), nullable=False),
        sa.Column("plan_version_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=True, unique=True),
        sa.Column("result_grant_id", sa.String(36), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("organization_id", "candidate_id", "created_by"):
        op.create_index(f"ix_company_assignments_{column}", "company_assignments", [column])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_assignments LIMIT 1")).first():
        raise RuntimeError("Cannot discard company assignments")
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
    op.drop_table("company_assignments")
