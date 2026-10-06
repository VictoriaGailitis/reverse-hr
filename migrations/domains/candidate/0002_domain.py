"""candidate-owned domain schema."""

import sqlalchemy as sa
from alembic import op

revision = "0002_candidate"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "candidate_profiles",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("display_name", sa.String(100), nullable=False),
        sa.Column("specialization", sa.String(100), nullable=False),
        sa.Column("declared_grade", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
    )


def downgrade():
    op.drop_table("candidate_profiles")
