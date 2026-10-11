"""Private verified source and pending evidence requirements."""

import sqlalchemy as sa
from alembic import op

revision = "0004_evaluation"
down_revision = "0003_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluation_intakes", sa.Column("source", sa.JSON()))
    op.add_column("evaluation_intakes", sa.Column("requirements", sa.JSON()))
    op.add_column(
        "evaluation_intakes",
        sa.Column("artifact_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "evaluation_intakes", sa.Column("artifact_available_at", sa.DateTime(timezone=True))
    )


def downgrade():
    bind = op.get_bind()
    if (
        bind.execute(sa.text("SELECT 1 FROM evaluation_intakes LIMIT 1")).first()
        or bind.execute(
            sa.text("SELECT 1 FROM evaluation_subjects WHERE blocked = true LIMIT 1")
        ).first()
    ):
        raise RuntimeError("Cannot downgrade populated Evaluation intake or tombstones")
    with op.batch_alter_table("evaluation_intakes") as batch:
        for column in ("source", "requirements", "artifact_attempts", "artifact_available_at"):
            batch.drop_column(column)
