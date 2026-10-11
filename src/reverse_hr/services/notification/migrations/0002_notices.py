"""Private dialog / notice state with guarded rollback."""

import sqlalchemy as sa
from alembic import op

revision = "0002_notification"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "notification_subjects",
        sa.Column("subject", sa.String(36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("request_id", sa.String(36), nullable=True, primary_key=False),
        sa.UniqueConstraint("request_id"),
    )
    op.create_table(
        "notification_notices",
        sa.Column("notice_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("recipient_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("invitation_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("creator_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("author_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(32), nullable=False, primary_key=False),
        sa.Column("read", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_index("ix_notification_notices_author_id", "notification_notices", ["author_id"])
    op.create_index("ix_notification_notices_creator_id", "notification_notices", ["creator_id"])
    op.create_index(
        "ix_notification_notices_candidate_id", "notification_notices", ["candidate_id"]
    )
    op.create_index(
        "ix_notification_notices_invitation_id", "notification_notices", ["invitation_id"]
    )
    op.create_index(
        "ix_notification_notices_recipient_id", "notification_notices", ["recipient_id"]
    )
    op.create_table(
        "notification_preferences",
        sa.Column("subject", sa.String(36), nullable=False, primary_key=True),
        sa.Column("in_app", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM notification_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM notification_notices LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM notification_preferences LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    op.drop_table("notification_preferences")
    op.drop_table("notification_notices")
    op.drop_table("notification_subjects")
