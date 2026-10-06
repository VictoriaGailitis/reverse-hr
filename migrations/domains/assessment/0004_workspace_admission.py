"""Replay protection for signed workspace stage admission."""

import sqlalchemy as sa
from alembic import op

revision = "0004_assessment"
down_revision = "0003_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "stage_nonces",
        sa.Column("nonce", sa.String(36), primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM stage_nonces LIMIT 1")).first():
        raise RuntimeError("Cannot discard active stage replay protection")
    op.drop_table("stage_nonces")
