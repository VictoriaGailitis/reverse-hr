"""privacy-owned domain schema."""

import sqlalchemy as sa
from alembic import op

revision = "0002_privacy"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "consents",
        sa.Column("consent_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("purpose", sa.String(50), nullable=False),
        sa.Column("document_version", sa.String(100), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_consents_candidate_id", "consents", ["candidate_id"])


def downgrade():
    op.drop_index("ix_consents_candidate_id", table_name="consents")
    op.drop_table("consents")
