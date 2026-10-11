"""Private dialog / notice state with guarded rollback."""

import sqlalchemy as sa
from alembic import op

revision = "0003_hiring"
down_revision = "0002_hiring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_dialogs",
        sa.Column("dialog_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_table(
        "hiring_employer_blocks",
        sa.Column("candidate_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(36), nullable=False, primary_key=True),
    )
    op.create_table(
        "hiring_messages",
        sa.Column("message_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("dialog_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("author_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("text", sa.String(4000), nullable=False, primary_key=False),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("dialog_id", "sequence"),
    )
    op.create_index("ix_hiring_messages_author_id", "hiring_messages", ["author_id"])
    op.create_index("ix_hiring_messages_dialog_id", "hiring_messages", ["dialog_id"])
    op.create_table(
        "hiring_complaints",
        sa.Column("complaint_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("dialog_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("author_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("message_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("reason", sa.String(2000), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_index("ix_hiring_complaints_author_id", "hiring_complaints", ["author_id"])
    op.create_index("ix_hiring_complaints_dialog_id", "hiring_complaints", ["dialog_id"])
    op.create_table(
        "hiring_notices",
        sa.Column("notice_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("invitation_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("recipient_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("author_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(32), nullable=False, primary_key=False),
    )
    op.create_index("ix_hiring_notices_author_id", "hiring_notices", ["author_id"])
    op.create_index("ix_hiring_notices_invitation_id", "hiring_notices", ["invitation_id"])
    op.create_index("ix_hiring_notices_recipient_id", "hiring_notices", ["recipient_id"])
    op.execute(
        sa.text(
            "INSERT INTO hiring_dialogs (dialog_id, version, sequence) "
            "SELECT invitation_id, 1, 0 FROM hiring_invitations WHERE status = 'accepted'"
        )
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM hiring_dialogs LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM hiring_employer_blocks LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM hiring_messages LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM hiring_complaints LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM hiring_notices LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated dialog/notification data")
    op.drop_table("hiring_notices")
    op.drop_table("hiring_complaints")
    op.drop_table("hiring_messages")
    op.drop_table("hiring_employer_blocks")
    op.drop_table("hiring_dialogs")
