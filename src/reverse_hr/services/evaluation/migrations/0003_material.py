"""Private pinned material with bounded preparation retry state."""

import sqlalchemy as sa
from alembic import op

revision = "0003_evaluation"
down_revision = "0002_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluation_intakes", sa.Column("material", sa.JSON()))
    op.add_column(
        "evaluation_intakes",
        sa.Column("material_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "evaluation_intakes", sa.Column("material_available_at", sa.DateTime(timezone=True))
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
        batch.drop_column("material")
        batch.drop_column("material_attempts")
        batch.drop_column("material_available_at")
