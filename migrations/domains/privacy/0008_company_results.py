"""Explicit recipient-scoped company result grants."""

import sqlalchemy as sa
from alembic import op

revision = "0008_privacy"
down_revision = "0007_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "company_result_grants",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("assignment_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("consent_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    for column in ("candidate_id", "assignment_id"):
        op.create_index(f"ix_company_result_grants_{column}", "company_result_grants", [column])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM company_result_grants LIMIT 1")).first():
        raise RuntimeError("Cannot discard company result grants")
    if op.get_bind().execute(sa.text("SELECT 1 FROM deletion_requests LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade a populated deletion ledger")
    if op.get_bind().execute(sa.text("SELECT 1 FROM backup_store_identity LIMIT 1")).first():
        raise RuntimeError("Cannot discard a registered backup archive")
    op.drop_table("company_result_grants")
