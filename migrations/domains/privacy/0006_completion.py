"""Record completed local cleanup separately from externally claimed status."""

import sqlalchemy as sa
from alembic import op

revision = "0006_privacy"
down_revision = "0005_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("deletion_requests", sa.Column("completed_at", sa.DateTime(timezone=True)))


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM deletion_requests LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade a populated deletion ledger")
    op.drop_column("deletion_requests", "completed_at")
