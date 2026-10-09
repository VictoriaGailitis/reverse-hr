"""Service/marketing preferences and company assignment notification references."""

import sqlalchemy as sa
from alembic import op

revision = "0003_notification"
down_revision = "0002_notification"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("notification_notices") as batch:
        batch.alter_column("invitation_id", existing_type=sa.String(36), nullable=True)
        batch.add_column(sa.Column("assignment_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("owner", sa.String(16), nullable=False, server_default="hiring"))
        batch.add_column(
            sa.Column("category", sa.String(16), nullable=False, server_default="service")
        )
        batch.create_index("ix_notification_notices_assignment_id", ["assignment_id"])
    op.add_column(
        "notification_preferences",
        sa.Column("marketing_in_app", sa.Boolean(), nullable=False, server_default=sa.false()),
    )


def downgrade():
    bind = op.get_bind()
    for table in ("notification_notices", "notification_preferences"):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated dialog/notification data")
    if bind.execute(
        sa.text("SELECT 1 FROM notification_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    op.drop_column("notification_preferences", "marketing_in_app")
    with op.batch_alter_table("notification_notices") as batch:
        batch.drop_index("ix_notification_notices_assignment_id")
        batch.drop_column("assignment_id")
        batch.drop_column("owner")
        batch.drop_column("category")
        batch.alter_column("invitation_id", existing_type=sa.String(36), nullable=False)
