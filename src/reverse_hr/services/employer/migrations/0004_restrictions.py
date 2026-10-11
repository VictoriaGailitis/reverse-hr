"""Employer restrictions and unresolved retained records."""

import sqlalchemy as sa
from alembic import op

revision = "0004_employer"
down_revision = "0003_employer"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "employer_subjects",
        sa.Column("subject", sa.String(36), primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("request_id", sa.String(36), unique=True),
        sa.Column("status", sa.String(16)),
        sa.Column("restricted_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM employer_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade populated Employer restrictions")
    op.drop_table("employer_subjects")
