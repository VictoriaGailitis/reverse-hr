"""Private blob references and server decode metadata; legacy database bytes remain readable."""

import sqlalchemy as sa
from alembic import op

revision = "0004_media"
down_revision = "0003_media"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_storage_identity",
        sa.Column("name", sa.String(16), primary_key=True),
        sa.Column("identity", sa.String(36), nullable=False),
    )
    with op.batch_alter_table("recordings") as batch:
        batch.add_column(sa.Column("validation", sa.JSON(), nullable=True))
    with op.batch_alter_table("recording_chunks") as batch:
        batch.alter_column("data", existing_type=sa.LargeBinary(), nullable=True)
        batch.add_column(sa.Column("object_key", sa.String(134), nullable=True))
        batch.add_column(sa.Column("byte_size", sa.Integer(), nullable=True))


def downgrade():
    bind = op.get_bind()
    if (
        bind.execute(sa.text("SELECT 1 FROM recordings LIMIT 1")).first()
        or bind.execute(sa.text("SELECT 1 FROM recording_chunks LIMIT 1")).first()
    ):
        raise RuntimeError("Cannot downgrade populated private media storage")
    if bind.execute(sa.text("SELECT 1 FROM media_subjects WHERE blocked = true LIMIT 1")).first():
        raise RuntimeError("Cannot discard media restrictions")
    with op.batch_alter_table("recording_chunks") as batch:
        batch.drop_column("byte_size")
        batch.drop_column("object_key")
        batch.alter_column("data", existing_type=sa.LargeBinary(), nullable=False)
    with op.batch_alter_table("recordings") as batch:
        batch.drop_column("validation")
    op.drop_table("media_storage_identity")
