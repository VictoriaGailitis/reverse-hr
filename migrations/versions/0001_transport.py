"""Per-service transport tables; no cross-service persistence."""

import sqlalchemy as sa
from alembic import op

revision = "0001_transport"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "outbox",
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("envelope", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_outbox_status", "outbox", ["status"])
    op.create_table(
        "inbox",
        sa.Column("consumer", sa.String(100), primary_key=True),
        sa.Column("event_id", sa.String(36), primary_key=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("actor_id", sa.String(100), nullable=False),
        sa.Column("operation", sa.String(150), nullable=False),
        sa.Column("key", sa.String(128), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("response", sa.Text(), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("actor_id", "operation", "key"),
    )


def downgrade():
    op.drop_table("idempotency_records")
    op.drop_table("inbox")
    op.drop_index("ix_outbox_status", table_name="outbox")
    op.drop_table("outbox")
