"""Immutable reviewed selection policies, parameter templates and variant provenance."""

import sqlalchemy as sa
from alembic import context, op

revision = "0017_assessment"
down_revision = "0016_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assessment_sessions", sa.Column("selection_policy_id", sa.String(36)))
    op.add_column("assessment_sessions", sa.Column("selection_policy_digest", sa.String(64)))
    op.add_column("assessment_sessions", sa.Column("selection_policy_snapshot", sa.JSON()))
    for name, key in (
        ("assessment_selection_policies", "policy_id"),
        ("assessment_variant_templates", "template_id"),
    ):
        op.create_table(
            name,
            sa.Column(key, sa.String(36), primary_key=True),
            sa.Column("data", sa.JSON(), nullable=False),
            sa.Column("status", sa.String(16), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("created_by", sa.String(36), nullable=False),
            sa.Column("reviewed_by", sa.String(36)),
            sa.Column("review_reason", sa.String(2000)),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_" + name + "_created_by", name, ["created_by"])
    op.create_table(
        "assessment_generated_variants",
        sa.Column("revision_id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(36), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("parameter_digest", sa.String(64), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("template_id", "parameter_digest"),
    )
    op.create_index(
        "ix_assessment_generated_variants_created_by",
        "assessment_generated_variants",
        ["created_by"],
    )


def downgrade():
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
    for table in (
        "assessment_generated_variants",
        "assessment_variant_templates",
        "assessment_selection_policies",
    ):
        op.drop_table(table)
    for column in ("selection_policy_snapshot", "selection_policy_digest", "selection_policy_id"):
        op.drop_column("assessment_sessions", column)
