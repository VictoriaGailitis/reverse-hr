"""Frozen trust, review and appeals storage."""

import sqlalchemy as sa
from alembic import context, op

revision = "0007_employer"
down_revision = "0006_employer"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "organizations",
        sa.Column("trust_required", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_table(
        "employer_trust_decisions",
        sa.Column("decision_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("dimension", sa.String(30), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("source", sa.String(30), nullable=False, primary_key=False),
        sa.Column("reason", sa.String(2000), nullable=False, primary_key=False),
        sa.Column("facts", sa.JSON(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_employer_trust_decisions_organization_id",
        "employer_trust_decisions",
        ["organization_id"],
    )
    op.create_index(
        "ix_employer_trust_decisions_reviewer_id", "employer_trust_decisions", ["reviewer_id"]
    )
    op.create_table(
        "employer_sanctions",
        sa.Column("sanction_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reason", sa.String(2000), nullable=False, primary_key=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_employer_sanctions_organization_id", "employer_sanctions", ["organization_id"]
    )
    op.create_index("ix_employer_sanctions_reviewer_id", "employer_sanctions", ["reviewer_id"])
    op.create_table(
        "employer_trust_appeals",
        sa.Column("appeal_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("target_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("author_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("data", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("target_id"),
    )
    op.create_index("ix_employer_trust_appeals_author_id", "employer_trust_appeals", ["author_id"])
    op.create_index(
        "ix_employer_trust_appeals_organization_id", "employer_trust_appeals", ["organization_id"]
    )
    op.create_index(
        "ix_employer_trust_appeals_reviewer_id", "employer_trust_appeals", ["reviewer_id"]
    )


def downgrade():
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
    op.drop_table("employer_trust_appeals")
    op.drop_table("employer_sanctions")
    op.drop_table("employer_trust_decisions")
    op.drop_column("organizations", "trust_required")
