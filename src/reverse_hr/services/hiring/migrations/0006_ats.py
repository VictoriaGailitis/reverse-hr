"""Minimal versioned external ATS status projection."""

import sqlalchemy as sa
from alembic import context, op

revision = "0006_hiring"
down_revision = "0005_hiring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_ats_statuses",
        sa.Column("job_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("invitation_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    for key in ("candidate_id", "organization_id", "invitation_id", "actor_id"):
        op.create_index("ix_hiring_ats_statuses_" + key, "hiring_ats_statuses", [key])


def downgrade():
    bind = op.get_bind()
    target = context.get_revision_argument()
    tables = ["hiring_ats_statuses"]
    if target != "0005_hiring":
        tables += [
            "hiring_vacancies",
            "hiring_vacancy_decisions",
            "hiring_applications",
            "hiring_application_changes",
        ]
    if target not in {"0005_hiring", "0004_hiring"}:
        tables += ["hiring_complaint_cases", "hiring_complaint_decisions"]
    if target not in {"0005_hiring", "0004_hiring", "0003_hiring"}:
        tables += [
            "hiring_dialogs",
            "hiring_messages",
            "hiring_employer_blocks",
            "hiring_complaints",
            "hiring_notices",
        ]
    if target not in {"0005_hiring", "0004_hiring", "0003_hiring", "0002_hiring"}:
        tables += ["hiring_needs", "hiring_invitations", "hiring_market_nonces"]
        if bind.execute(
            sa.text("SELECT 1 FROM hiring_subjects WHERE blocked = true LIMIT 1")
        ).first():
            raise RuntimeError("Cannot downgrade deletion tombstones")
    # Check the entire requested path before the first DDL, including SQLite.
    for table in tables:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Hiring data")
    op.drop_table("hiring_ats_statuses")
