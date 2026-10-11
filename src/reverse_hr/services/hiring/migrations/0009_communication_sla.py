"""Durable independent review SLA and private communication risk references."""

import sqlalchemy as sa
from alembic import context, op

revision = "0009_hiring"
down_revision = "0008_hiring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_review_pool",
        sa.Column("subject_id", sa.String(36), primary_key=True),
        sa.Column("available_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "hiring_review_sla",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_hiring_review_sla_owner_id", "hiring_review_sla", ["owner_id"])
    op.create_table(
        "hiring_review_actions",
        sa.Column("action_id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("recipient_id", sa.String(36)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    for key in ("case_id", "recipient_id"):
        op.create_index("ix_hiring_review_actions_" + key, "hiring_review_actions", [key])
    op.create_table(
        "hiring_communication_risks",
        sa.Column("message_id", sa.String(36), primary_key=True),
        sa.Column("dialog_id", sa.String(36), nullable=False),
        sa.Column("complaint_id", sa.String(36), nullable=False, unique=True),
        sa.Column("author_id", sa.String(36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
    )
    for key in ("dialog_id", "author_id"):
        op.create_index("ix_hiring_communication_risks_" + key, "hiring_communication_risks", [key])


def downgrade():
    bind = op.get_bind()
    for table in (
        "hiring_review_pool",
        "hiring_review_sla",
        "hiring_review_actions",
        "hiring_communication_risks",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Hiring review history")
    if context.get_revision_argument() != "0008_hiring":
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
        if target not in {
            "0007_hiring",
            "0006_hiring",
            "0005_hiring",
            "0004_hiring",
            "0003_hiring",
        }:
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
    op.drop_table("hiring_communication_risks")
    op.drop_table("hiring_review_actions")
    op.drop_table("hiring_review_sla")
    op.drop_table("hiring_review_pool")
