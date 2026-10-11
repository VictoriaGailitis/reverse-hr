"""Minimal application references in service notifications."""

import sqlalchemy as sa
from alembic import op

revision = "0004_notification"
down_revision = "0003_notification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("notification_notices", sa.Column("application_id", sa.String(36), nullable=True))
    op.create_index(
        "ix_notification_notices_application_id", "notification_notices", ["application_id"]
    )


def downgrade():
    bind = op.get_bind()
    for table in ("notification_notices", "notification_preferences"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated application notification data")
    if bind.execute(
        sa.text("SELECT 1 FROM notification_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated application notification data")
    op.drop_index("ix_notification_notices_application_id", table_name="notification_notices")
    op.drop_column("notification_notices", "application_id")
