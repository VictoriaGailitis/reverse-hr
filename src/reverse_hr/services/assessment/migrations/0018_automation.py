"""Original generation references, previews, leased jobs and automatic grade queues."""

import sqlalchemy as sa
from alembic import context, op

revision = "0018_assessment"
down_revision = "0017_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "grade_decisions",
        sa.Column("origin", sa.String(16), nullable=False, server_default="human"),
    )
    op.create_table(
        "assessment_automatic_reviews",
        sa.Column("session_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False, index=True),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("reasons", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("appeal_id", sa.String(36)),
        sa.Column("case_origin", sa.String(16)),
    )
    op.create_table(
        "assessment_generation_references",
        sa.Column("version_id", sa.String(36), primary_key=True),
        sa.Column("reference_id", sa.String(36), nullable=False, index=True),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("organization_id", sa.String(36), index=True),
        sa.Column("author_id", sa.String(36), nullable=False, index=True),
        sa.Column("approved_by", sa.String(36)),
        sa.Column("grading_policy_id", sa.String(36)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("reference_id", "number"),
    )
    op.create_table(
        "assessment_generation_previews",
        sa.Column("preview_id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False, index=True),
        sa.Column("author_id", sa.String(36), nullable=False, index=True),
        sa.Column("specification", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("generation_id", sa.String(36), unique=True),
    )
    op.create_table(
        "assessment_generation_jobs",
        sa.Column("generation_id", sa.String(36), primary_key=True),
        sa.Column("version_id", sa.String(36), nullable=False, index=True),
        sa.Column("author_id", sa.String(36), nullable=False, index=True),
        sa.Column("specification", sa.JSON(), nullable=False),
        sa.Column("specification_digest", sa.String(64), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("configuration", sa.JSON(), nullable=False),
        sa.Column("prompt_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("error", sa.String(100)),
        sa.Column("output", sa.JSON()),
        sa.Column("output_digest", sa.String(64), index=True),
        sa.Column("revision_id", sa.String(36), unique=True),
        sa.Column("suite_id", sa.String(36)),
        sa.Column("validation_id", sa.String(36), unique=True),
        sa.Column("runtime_fingerprint", sa.String(64)),
        sa.Column("plan_version_id", sa.String(36)),
        sa.Column("grade_policy_id", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_until", sa.DateTime(timezone=True)),
        sa.Column("lease_token", sa.String(36)),
    )


def downgrade():
    # Check older lifecycle guards before SQLite performs non-transactional DDL.
    if (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT 1 FROM assessment_sessions WHERE selection_policy_id IS NOT NULL LIMIT 1"
            )
        )
        .first()
    ):
        raise RuntimeError("Cannot discard populated Assessment selection history")
    if context.get_revision_argument() != "0016_assessment":
        # SQLite DDL is not transactional: check older domain guards before dropping new tables.
        for table in (
            "company_subscriptions",
            "company_schedules",
            "company_assignment_origins",
            "company_delivery_limits",
            "company_jobs",
            "company_notice_sources",
        ):
            if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
                raise RuntimeError("Cannot discard populated company scheduling data")
        for table in (
            "assessment_sessions",
            "content_revisions",
            "plan_versions",
            "grade_policies",
            "grade_decisions",
            "candidate_grades",
            "test_suites",
            "assessment_appeals",
            "company_assignments",
            "company_task_proposals",
            "company_subscriptions",
            "company_schedules",
            "assessment_review_pool",
            "assessment_review_sla",
            "assessment_review_actions",
        ):
            if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
                raise RuntimeError(
                    "Cannot downgrade populated assessment content"
                    if table == "content_revisions"
                    else "Cannot downgrade populated assessment lifecycle"
                )
        if (
            op.get_bind()
            .execute(sa.text("SELECT 1 FROM assessment_subjects WHERE blocked = true LIMIT 1"))
            .first()
        ):
            raise RuntimeError("Cannot discard assessment restrictions")
    for table in (
        "assessment_generated_variants",
        "assessment_variant_templates",
        "assessment_selection_policies",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot discard populated Assessment selection history")
    tables = (
        "assessment_generation_previews",
        "assessment_generation_jobs",
        "assessment_generation_references",
        "assessment_automatic_reviews",
    )
    for table in tables:
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot discard original generation or automatic review history")
    for table in tables:
        op.drop_table(table)
    op.drop_column("grade_decisions", "origin")
