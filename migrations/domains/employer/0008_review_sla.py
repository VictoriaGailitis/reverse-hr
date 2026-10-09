"""Durable independent review SLA and private communication risk references."""

import sqlalchemy as sa
from alembic import context, op

revision = "0008_employer"
down_revision = "0007_employer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employer_review_pool",
        sa.Column("subject_id", sa.String(36), primary_key=True),
        sa.Column("available_until", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "employer_review_sla",
        sa.Column("case_id", sa.String(36), primary_key=True),
        sa.Column("kind", sa.String(32), primary_key=True),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_employer_review_sla_owner_id", "employer_review_sla", ["owner_id"])
    op.create_table(
        "employer_review_actions",
        sa.Column("action_id", sa.String(36), primary_key=True),
        sa.Column("case_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("recipient_id", sa.String(36)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
    )
    for key in ("case_id", "recipient_id"):
        op.create_index("ix_employer_review_actions_" + key, "employer_review_actions", [key])


def downgrade():
    bind = op.get_bind()
    for table in ("employer_review_pool", "employer_review_sla", "employer_review_actions"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Employer review history")
    if context.get_revision_argument() != "0007_employer":
        bind = op.get_bind()
        if bind.execute(
            sa.text("SELECT 1 FROM organizations WHERE trust_required = true LIMIT 1")
        ).first():
            raise RuntimeError("Cannot downgrade new trust verification restrictions")
        if bind.execute(sa.text("SELECT 1 FROM employer_trust_decisions LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated trust history")
        if bind.execute(sa.text("SELECT 1 FROM employer_sanctions LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated trust history")
        if bind.execute(sa.text("SELECT 1 FROM employer_trust_appeals LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated trust history")
        if context.get_revision_argument() != "0006_employer":
            for table in (
                "organizations",
                "memberships",
                "verification_decisions",
                "ownership_recoveries",
            ):
                if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
                    raise RuntimeError("Cannot downgrade populated Employer history")
            if bind.execute(
                sa.text("SELECT 1 FROM employer_subjects WHERE blocked = true LIMIT 1")
            ).first():
                raise RuntimeError("Cannot downgrade populated Employer restrictions")
    op.drop_table("employer_review_actions")
    op.drop_table("employer_review_sla")
    op.drop_table("employer_review_pool")
