"""Immutable appeals, independent review and revised grade decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0015_assessment"
down_revision = "0014_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assessment_appeals",
        sa.Column("appeal_id", sa.String(length=36), primary_key=True),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("decision_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("reason", sa.String(length=5000), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36)),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("filing_deadline", sa.DateTime(timezone=True), nullable=False),
        sa.Column("review_due_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("decision_id"),
    )
    op.create_index(
        "ix_assessment_appeals_candidate_id", "assessment_appeals", ["candidate_id"], unique=False
    )
    op.create_index(
        "ix_assessment_appeals_reviewer_id", "assessment_appeals", ["reviewer_id"], unique=False
    )
    op.create_index(
        "ix_assessment_appeals_session_id", "assessment_appeals", ["session_id"], unique=True
    )
    op.create_table(
        "assessment_appeal_actions",
        sa.Column("action_id", sa.String(length=36), primary_key=True),
        sa.Column("appeal_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(length=24), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("appeal_id", "version"),
    )
    op.create_index(
        "ix_assessment_appeal_actions_actor_id",
        "assessment_appeal_actions",
        ["actor_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_appeal_actions_appeal_id",
        "assessment_appeal_actions",
        ["appeal_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_appeal_actions_candidate_id",
        "assessment_appeal_actions",
        ["candidate_id"],
        unique=False,
    )
    op.create_table(
        "assessment_appeal_decisions",
        sa.Column("decision_id", sa.String(length=36), primary_key=True),
        sa.Column("appeal_id", sa.String(length=36), nullable=False),
        sa.Column("original_decision_id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False),
        sa.Column("session_version", sa.Integer(), nullable=False),
        sa.Column("previous_session_version", sa.Integer(), nullable=False),
        sa.Column("specialization", sa.String(length=100), nullable=False),
        sa.Column("target_grade", sa.String(length=16), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("competency_scores", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(length=2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_grade", sa.String(length=16)),
        sa.UniqueConstraint("original_decision_id"),
        sa.UniqueConstraint("appeal_id"),
    )
    op.create_index(
        "ix_assessment_appeal_decisions_candidate_id",
        "assessment_appeal_decisions",
        ["candidate_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_appeal_decisions_reviewer_id",
        "assessment_appeal_decisions",
        ["reviewer_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_appeal_decisions_session_id",
        "assessment_appeal_decisions",
        ["session_id"],
        unique=False,
    )
    op.create_table(
        "assessment_appeal_notices",
        sa.Column("notice_id", sa.String(length=36), primary_key=True),
        sa.Column("appeal_id", sa.String(length=36), nullable=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("author_id", sa.String(length=36), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
    )
    op.create_index(
        "ix_assessment_appeal_notices_appeal_id",
        "assessment_appeal_notices",
        ["appeal_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_appeal_notices_author_id",
        "assessment_appeal_notices",
        ["author_id"],
        unique=False,
    )
    op.create_index(
        "ix_assessment_appeal_notices_candidate_id",
        "assessment_appeal_notices",
        ["candidate_id"],
        unique=False,
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM assessment_appeals LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated appeals")
    if op.get_bind().execute(sa.text("SELECT 1 FROM assessment_appeal_actions LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated appeals")
    if op.get_bind().execute(sa.text("SELECT 1 FROM assessment_appeal_decisions LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated appeals")
    if op.get_bind().execute(sa.text("SELECT 1 FROM assessment_appeal_notices LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated appeals")
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
    op.drop_table("assessment_appeal_notices")
    op.drop_table("assessment_appeal_decisions")
    op.drop_table("assessment_appeal_actions")
    op.drop_table("assessment_appeals")
