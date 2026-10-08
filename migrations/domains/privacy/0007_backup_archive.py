"""Pin the backup archive so a missing/replaced bucket cannot bypass erasure."""

import sqlalchemy as sa
from alembic import op

revision = "0007_privacy"
down_revision = "0006_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "backup_store_identity",
        sa.Column("name", sa.String(16), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
    )

    op.add_column(
        "deletion_requests",
        sa.Column("backup_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "deletion_requests", sa.Column("backup_retry_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("deletion_requests", sa.Column("backup_error", sa.String(32), nullable=True))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM deletion_requests LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade a populated deletion ledger")
    if op.get_bind().execute(sa.text("SELECT 1 FROM backup_store_identity LIMIT 1")).first():
        raise RuntimeError("Cannot discard a registered backup archive")
    op.drop_column("deletion_requests", "backup_error")
    op.drop_column("deletion_requests", "backup_retry_at")
    op.drop_column("deletion_requests", "backup_attempts")
    op.drop_table("backup_store_identity")
