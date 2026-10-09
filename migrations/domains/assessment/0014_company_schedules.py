"""Durable company subscription epochs, schedules, jobs and minimal notice sources."""

import sqlalchemy as sa
from alembic import op

revision = "0014_assessment"
down_revision = "0013_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_subscriptions",
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("consent_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("min_interval_seconds", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_table(
        "company_schedules",
        sa.Column("schedule_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(36), nullable=False, primary_key=False),
        sa.Column("proposal_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("plan_version_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("subscription_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("interval_seconds", sa.Integer(), nullable=True, primary_key=False),
        sa.Column("max_occurrences", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("issued_count", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("expires_in_days", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("organization_id", "candidate_id", "plan_version_id", "starts_at"),
    )
    op.create_index("ix_company_schedules_candidate_id", "company_schedules", ["candidate_id"])
    op.create_index("ix_company_schedules_created_by", "company_schedules", ["created_by"])
    op.create_index(
        "ix_company_schedules_organization_id", "company_schedules", ["organization_id"]
    )
    op.create_table(
        "company_assignment_origins",
        sa.Column("assignment_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("schedule_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("subscription_version", sa.Integer(), nullable=True, primary_key=False),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_company_assignment_origins_candidate_id", "company_assignment_origins", ["candidate_id"]
    )
    op.create_index(
        "ix_company_assignment_origins_created_by", "company_assignment_origins", ["created_by"]
    )
    op.create_table(
        "company_delivery_limits",
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("last_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "company_jobs",
        sa.Column("job_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("dedupe_key", sa.String(100), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("schedule_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("assignment_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("kind", sa.String(24), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("attempts", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("error", sa.String(32), nullable=True, primary_key=False),
        sa.UniqueConstraint("dedupe_key"),
    )
    op.create_index("ix_company_jobs_candidate_id", "company_jobs", ["candidate_id"])
    op.create_index("ix_company_jobs_created_by", "company_jobs", ["created_by"])
    op.create_index("ix_company_jobs_next_at", "company_jobs", ["next_at"])
    op.create_table(
        "company_notice_sources",
        sa.Column("notice_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("assignment_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("created_by", sa.String(36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("recipient_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(24), nullable=False, primary_key=False),
        sa.Column("category", sa.String(16), nullable=False, primary_key=False),
        sa.Column("subscription_version", sa.Integer(), nullable=True, primary_key=False),
        sa.UniqueConstraint("assignment_id", "recipient_id", "kind"),
    )
    op.create_index(
        "ix_company_notice_sources_assignment_id", "company_notice_sources", ["assignment_id"]
    )
    op.create_index(
        "ix_company_notice_sources_candidate_id", "company_notice_sources", ["candidate_id"]
    )
    op.create_index(
        "ix_company_notice_sources_created_by", "company_notice_sources", ["created_by"]
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_subscriptions LIMIT 1")).first():
        raise RuntimeError("Cannot discard populated company scheduling data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_schedules LIMIT 1")).first():
        raise RuntimeError("Cannot discard populated company scheduling data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_assignment_origins LIMIT 1")).first():
        raise RuntimeError("Cannot discard populated company scheduling data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_delivery_limits LIMIT 1")).first():
        raise RuntimeError("Cannot discard populated company scheduling data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_jobs LIMIT 1")).first():
        raise RuntimeError("Cannot discard populated company scheduling data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_notice_sources LIMIT 1")).first():
        raise RuntimeError("Cannot discard populated company scheduling data")
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
    op.drop_table("company_notice_sources")
    op.drop_table("company_jobs")
    op.drop_table("company_delivery_limits")
    op.drop_table("company_assignment_origins")
    op.drop_table("company_schedules")
    op.drop_table("company_subscriptions")
