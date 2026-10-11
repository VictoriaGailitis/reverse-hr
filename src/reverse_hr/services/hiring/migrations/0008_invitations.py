"""Immutable invitation terms and replacement lineage."""

import sqlalchemy as sa
from alembic import context, op

revision = "0008_hiring"
down_revision = "0007_hiring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_invitation_revisions",
        sa.Column("invitation_id", sa.String(36), primary_key=True),
        sa.Column("version", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("created_by", sa.String(36), nullable=False),
        sa.Column("predecessor_id", sa.String(36)),
        sa.Column("terms", sa.JSON(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
    )
    for key in ("candidate_id", "created_by"):
        op.create_index(
            "ix_hiring_invitation_revisions_" + key, "hiring_invitation_revisions", [key]
        )
    # Existing sent offers retain the concrete terms originally persisted in Hiring.
    op.execute(
        sa.text(
            "INSERT INTO hiring_invitation_revisions "
            "(invitation_id, version, candidate_id, created_by, terms, recorded_at) "
            "SELECT invitation_id, version, candidate_id, created_by, spec, "
            "CURRENT_TIMESTAMP FROM hiring_invitations"
        )
    )


def downgrade():
    bind = op.get_bind()
    target = context.get_revision_argument()
    tables = ["hiring_invitation_revisions"]
    if target != "0007_hiring":
        tables += ["hiring_employer_reviews", "hiring_moderation_appeals"]
    if target not in {"0007_hiring", "0006_hiring"}:
        tables += ["hiring_ats_statuses"]
    if target not in {"0007_hiring", "0006_hiring", "0005_hiring"}:
        tables += [
            "hiring_vacancies",
            "hiring_vacancy_decisions",
            "hiring_applications",
            "hiring_application_changes",
        ]
    if target not in {"0007_hiring", "0006_hiring", "0005_hiring", "0004_hiring"}:
        tables += ["hiring_complaint_cases", "hiring_complaint_decisions"]
    if target not in {"0007_hiring", "0006_hiring", "0005_hiring", "0004_hiring", "0003_hiring"}:
        tables += [
            "hiring_dialogs",
            "hiring_messages",
            "hiring_employer_blocks",
            "hiring_complaints",
            "hiring_notices",
        ]
    if target not in {
        "0007_hiring",
        "0006_hiring",
        "0005_hiring",
        "0004_hiring",
        "0003_hiring",
        "0002_hiring",
    }:
        tables += ["hiring_needs", "hiring_invitations", "hiring_market_nonces"]
        if bind.execute(
            sa.text("SELECT 1 FROM hiring_subjects WHERE blocked = true LIMIT 1")
        ).first():
            raise RuntimeError("Cannot downgrade deletion tombstones")
    for table in tables:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Hiring data")
    op.drop_table("hiring_invitation_revisions")
