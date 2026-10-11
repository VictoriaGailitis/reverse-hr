"""Service-owned recruitment state; protect data before downgrade DDL."""

import sqlalchemy as sa
from alembic import op

revision = "0006_employer"
down_revision = "0005_employer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employer_market_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM ownership_recoveries LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated ownership recovery history")
    for table in (
        "employer_market_nonces",
        "organizations",
        "memberships",
        "verification_decisions",
        "ownership_recoveries",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated recruitment data")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM employer_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade populated Employer restrictions")
    op.drop_table("employer_market_nonces")
