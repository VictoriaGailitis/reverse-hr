"""employer-owned domain schema."""

import sqlalchemy as sa
from alembic import op

revision = "0002_employer"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "organizations",
        sa.Column("organization_id", sa.String(36), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("verification_status", sa.String(16), nullable=False),
        sa.Column("verification_reason", sa.String(2000), nullable=True),
        sa.Column("verified_by", sa.String(36), nullable=True),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_table(
        "memberships",
        sa.Column("membership_id", sa.String(36), primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("subject", sa.String(36), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.UniqueConstraint("organization_id", "subject"),
    )
    op.create_index("ix_memberships_organization_id", "memberships", ["organization_id"])
    op.create_index("ix_memberships_subject", "memberships", ["subject"])


def downgrade():
    op.drop_index("ix_memberships_organization_id", table_name="memberships")
    op.drop_index("ix_memberships_subject", table_name="memberships")
    op.drop_table("memberships")
    op.drop_table("organizations")
