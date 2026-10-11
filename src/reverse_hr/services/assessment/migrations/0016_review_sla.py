"""Durable independent review SLA and private communication risk references."""

import sqlalchemy as sa
from alembic import context, op

revision = "0016_assessment"
down_revision = "0015_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assessment_review_pool",
        sa.Column("subject_id", sa.String(36), primary_key=True),
        sa.Column("available_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "assessment_review_sla",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_assessment_review_sla_owner_id", "assessment_review_sla", ["owner_id"])
    op.create_table(
        "assessment_review_actions",
        sa.Column("action_id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("recipient_id", sa.String(36)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    for key in ("case_id", "recipient_id"):
        op.create_index("ix_assessment_review_actions_" + key, "assessment_review_actions", [key])


def downgrade():
    bind = op.get_bind()
    for table in ("assessment_review_pool", "assessment_review_sla", "assessment_review_actions"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Assessment review history")
    if context.get_revision_argument() != "0015_assessment":
        if op.get_bind().execute(sa.text("SELECT 1 FROM assessment_appeals LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated appeals")
        if (
            op.get_bind()
            .execute(sa.text("SELECT 1 FROM assessment_appeal_actions LIMIT 1"))
            .first()
        ):
            raise RuntimeError("Cannot downgrade populated appeals")
        if (
            op.get_bind()
            .execute(sa.text("SELECT 1 FROM assessment_appeal_decisions LIMIT 1"))
            .first()
        ):
            raise RuntimeError("Cannot downgrade populated appeals")
        if (
            op.get_bind()
            .execute(sa.text("SELECT 1 FROM assessment_appeal_notices LIMIT 1"))
            .first()
        ):
            raise RuntimeError("Cannot downgrade populated appeals")
        if op.get_bind().execute(sa.text("SELECT 1 FROM company_subscriptions LIMIT 1")).first():
            raise RuntimeError("Cannot discard populated company scheduling data")
        if op.get_bind().execute(sa.text("SELECT 1 FROM company_schedules LIMIT 1")).first():
            raise RuntimeError("Cannot discard populated company scheduling data")
        if (
            op.get_bind()
            .execute(sa.text("SELECT 1 FROM company_assignment_origins LIMIT 1"))
            .first()
        ):
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
    op.drop_table("assessment_review_actions")
    op.drop_table("assessment_review_sla")
    op.drop_table("assessment_review_pool")
