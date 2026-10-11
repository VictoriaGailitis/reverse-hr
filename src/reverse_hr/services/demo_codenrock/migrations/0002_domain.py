"""Frozen schema for source-scoped achievements and demo exchanges."""

import sqlalchemy as sa
from alembic import op

revision = "0002_demo_codenrock"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "demo_source_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM demo_source_nonces LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated demo-codenrock data")
    op.drop_table("demo_source_nonces")
