"""History of moderation and persistent revoked memberships."""

import sqlalchemy as sa
from alembic import op

revision = "0003_employer"
down_revision = "0002_employer"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "memberships", sa.Column("status", sa.String(16), nullable=False, server_default="active")
    )
    op.add_column(
        "memberships", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    op.create_table(
        "verification_decisions",
        sa.Column("decision_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("reason", sa.String(2000), nullable=False),
        sa.Column("source", sa.String(30), nullable=False),
        sa.Column("organization_version", sa.Integer(), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_verification_decisions_organization_id", "verification_decisions", ["organization_id"]
    )


def downgrade():
    op.drop_index("ix_verification_decisions_organization_id", table_name="verification_decisions")
    op.drop_table("verification_decisions")
    op.drop_column("memberships", "version")
    op.drop_column("memberships", "status")
