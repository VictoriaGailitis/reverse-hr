"""Private review/proposal state with data-preserving rollback guard."""

import sqlalchemy as sa
from alembic import op

revision = "0004_hiring"
down_revision = "0003_hiring"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "hiring_complaint_cases",
        sa.Column("complaint_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_table(
        "hiring_complaint_decisions",
        sa.Column("decision_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("complaint_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("outcome", sa.String(16), nullable=False, primary_key=False),
        sa.Column("reason", sa.String(2000), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("complaint_id", "version"),
    )
    op.create_index(
        "ix_hiring_complaint_decisions_complaint_id", "hiring_complaint_decisions", ["complaint_id"]
    )
    op.create_index(
        "ix_hiring_complaint_decisions_reviewer_id", "hiring_complaint_decisions", ["reviewer_id"]
    )
    op.execute(
        sa.text(
            "INSERT INTO hiring_complaint_cases (complaint_id, status, version) "
            "SELECT complaint_id, 'open', 1 FROM hiring_complaints"
        )
    )


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM hiring_complaint_cases LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated review/proposal data")
    if op.get_bind().execute(sa.text("SELECT 1 FROM hiring_complaint_decisions LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated review/proposal data")
    op.drop_table("hiring_complaint_decisions")
    op.drop_table("hiring_complaint_cases")
