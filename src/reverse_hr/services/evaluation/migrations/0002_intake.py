"""Private Evaluation intake and permanent deletion tombstones."""

import sqlalchemy as sa
from alembic import op

revision = "0002_evaluation"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "evaluation_subjects",
        sa.Column("candidate_id", sa.String(36), primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False),
        sa.Column("deletion_request_id", sa.String(36), unique=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True)),
    )
    op.create_table(
        "evaluation_intakes",
        sa.Column("stage_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("session_id", sa.String(36), nullable=False),
        sa.Column("workspace_id", sa.String(36), nullable=False),
        sa.Column("snapshot_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    for name in ("candidate_id", "session_id"):
        op.create_index(f"ix_evaluation_intakes_{name}", "evaluation_intakes", [name])


def downgrade():
    bind = op.get_bind()
    if (
        bind.execute(sa.text("SELECT 1 FROM evaluation_intakes LIMIT 1")).first()
        or bind.execute(
            sa.text("SELECT 1 FROM evaluation_subjects WHERE blocked = true LIMIT 1")
        ).first()
    ):
        raise RuntimeError("Cannot downgrade populated Evaluation intake or tombstones")
    op.drop_table("evaluation_intakes")
    op.drop_table("evaluation_subjects")
