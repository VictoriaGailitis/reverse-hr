"""Privacy deletion coordination and durable processing restrictions."""

import sqlalchemy as sa
from alembic import op

revision = "0004_privacy"
down_revision = "0003_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "privacy_subjects",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
    )
    op.create_table(
        "deletion_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), unique=True, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "deletion_targets",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("service", sa.String(50), primary_key=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    # Never silently drop a deletion ledger and permit data resurrection.
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM deletion_requests LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade a populated deletion ledger")
    op.drop_table("deletion_targets")
    op.drop_table("deletion_requests")
    op.drop_table("privacy_subjects")
