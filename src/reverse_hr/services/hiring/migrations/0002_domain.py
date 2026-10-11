"""Service-owned recruitment state; protect data before downgrade DDL."""

import sqlalchemy as sa
from alembic import op

revision = "0002_hiring"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, unique=True),
    )
    op.create_table(
        "hiring_market_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "hiring_needs",
        sa.Column("need_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )
    op.create_index("ix_hiring_needs_created_by", "hiring_needs", ["created_by"])
    op.create_index("ix_hiring_needs_organization_id", "hiring_needs", ["organization_id"])
    op.create_table(
        "hiring_invitations",
        sa.Column("invitation_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("created_by", sa.String(length=36), nullable=False),
        sa.Column("spec", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consent_id", sa.String(length=36), nullable=True),
    )
    op.create_index("ix_hiring_invitations_candidate_id", "hiring_invitations", ["candidate_id"])
    op.create_index("ix_hiring_invitations_created_by", "hiring_invitations", ["created_by"])
    op.create_index(
        "ix_hiring_invitations_organization_id", "hiring_invitations", ["organization_id"]
    )


def downgrade():
    for table in ("hiring_market_nonces", "hiring_needs", "hiring_invitations"):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated recruitment data")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM hiring_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade deletion tombstones")
    op.drop_table("hiring_invitations")
    op.drop_table("hiring_needs")
    op.drop_table("hiring_market_nonces")
    op.drop_table("hiring_subjects")
