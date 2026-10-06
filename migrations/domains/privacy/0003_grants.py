"""Company-specific grants with revocation tombstones."""

import sqlalchemy as sa
from alembic import op

revision = "0003_privacy"
down_revision = "0002_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "contact_grants",
        sa.Column("grant_id", sa.String(36), primary_key=True),
        sa.Column("invitation_id", sa.String(36), nullable=False, unique=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("organization_id", sa.String(36), nullable=False),
        sa.Column("consent_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True)),
    )
    op.create_index("ix_contact_grants_candidate_id", "contact_grants", ["candidate_id"])
    op.create_index("ix_contact_grants_consent_id", "contact_grants", ["consent_id"])


def downgrade():
    op.drop_index("ix_contact_grants_consent_id", table_name="contact_grants")
    op.drop_index("ix_contact_grants_candidate_id", table_name="contact_grants")
    op.drop_table("contact_grants")
