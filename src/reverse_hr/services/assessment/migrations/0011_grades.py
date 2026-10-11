"""Calibrated grade policies and human session decisions."""

import sqlalchemy as sa
from alembic import op

revision = "0011_assessment"
down_revision = "0010_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assessment_sessions", sa.Column("grade_policy_id", sa.String(36)))
    op.add_column("assessment_sessions", sa.Column("grade_policy_digest", sa.String(64)))
    op.create_table(
        "grade_policies",
        sa.Column("policy_id", sa.String(36), primary_key=True),
        sa.Column("plan_version_id", sa.String(36), nullable=False),
        sa.Column("plan_digest", sa.String(64), nullable=False),
        sa.Column("rules", sa.JSON(), nullable=False),
        sa.Column("rules_digest", sa.String(64), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("approved_by", sa.String(36)),
        sa.Column("retired_by", sa.String(36)),
        sa.Column("retirement_reason", sa.String(2000)),
        sa.Column("calibration", sa.JSON()),
        sa.Column("calibration_digest", sa.String(64)),
        sa.Column("approved_at", sa.DateTime(timezone=True)),
    )
    for name in ("plan_version_id", "created_by", "approved_by"):
        op.create_index(f"ix_grade_policies_{name}", "grade_policies", [name])
    op.create_table(
        "grade_decisions",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        *[
            sa.Column(name, sa.String(36), nullable=False)
            for name in ("session_id", "candidate_id", "reviewer_id")
        ],
        sa.Column("specialization", sa.String(100), nullable=False),
        sa.Column("target_grade", sa.String(16), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("score", sa.Integer()),
        sa.Column("competency_scores", sa.JSON(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_grade", sa.String(16)),
        sa.UniqueConstraint("session_id"),
    )
    for name in ("session_id", "candidate_id", "reviewer_id"):
        op.create_index(f"ix_grade_decisions_{name}", "grade_decisions", [name])
    op.create_table(
        "candidate_grades",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("specialization", sa.String(100), primary_key=True),
        sa.Column("grade", sa.String(16), nullable=False),
        sa.Column("decision_id", sa.String(36), nullable=False),
        sa.Column("changed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("change_available_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
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
    op.drop_table("candidate_grades")
    op.drop_table("grade_decisions")
    op.drop_table("grade_policies")
    op.drop_column("assessment_sessions", "grade_policy_digest")
    op.drop_column("assessment_sessions", "grade_policy_id")
