"""Candidate restriction tombstones survive profile erasure."""

import sqlalchemy as sa
from alembic import op

revision = "0003_candidate"
down_revision = "0002_candidate"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_subjects",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("deletion_request_id", sa.String(36), unique=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )


def downgrade():
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM candidate_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade populated Candidate deletion tombstones")
    op.drop_table("candidate_subjects")
