"""Short-lived replay protection for signed processing-status requests."""

import sqlalchemy as sa
from alembic import op

revision = "0005_privacy"
down_revision = "0004_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "processing_nonces",
        sa.Column("requester", sa.String(50), primary_key=True),
        sa.Column("nonce", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_processing_nonces_expires_at", "processing_nonces", ["expires_at"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM deletion_requests LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade a populated deletion ledger")
    op.drop_index("ix_processing_nonces_expires_at", table_name="processing_nonces")
    op.drop_table("processing_nonces")
