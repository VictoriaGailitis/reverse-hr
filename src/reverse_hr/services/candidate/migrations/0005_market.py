"""Service-owned recruitment state; protect data before downgrade DDL."""

import sqlalchemy as sa
from alembic import op

revision = "0005_candidate"
down_revision = "0004_candidate"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_publication",
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("published", sa.Boolean(), nullable=False),
        sa.Column("consent_id", sa.String(length=36), nullable=True),
        sa.Column("declared_skills", sa.JSON(), nullable=False),
    )
    op.create_table(
        "candidate_contacts",
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
    )
    op.create_table(
        "candidate_market_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    for table in (
        "candidate_publication",
        "candidate_contacts",
        "candidate_market_nonces",
        "candidate_grade_history",
        "candidate_profiles",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated recruitment data")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM candidate_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade deletion tombstones")
    op.drop_table("candidate_market_nonces")
    op.drop_table("candidate_contacts")
    op.drop_table("candidate_publication")
