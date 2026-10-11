"""Auditable recovery after restriction of an organization owner."""

import sqlalchemy as sa
from alembic import op

revision = "0005_employer"
down_revision = "0004_employer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ownership_recoveries",
        sa.Column("recovery_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("previous_membership_id", sa.String(36), nullable=False),
        sa.Column("new_membership_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("organization_version", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    for field in ("organization_id", "reviewer_id"):
        op.create_index(f"ix_ownership_recoveries_{field}", "ownership_recoveries", [field])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM ownership_recoveries LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated ownership recovery history")
    op.drop_table("ownership_recoveries")
