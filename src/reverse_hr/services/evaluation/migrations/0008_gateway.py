"""Pin public provider limits and tariffs; never persist a credential."""

import sqlalchemy as sa
from alembic import op

revision = "0008_evaluation"
down_revision = "0007_evaluation"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("evaluation_model_attempts", sa.Column("gateway_configuration", sa.JSON()))


def downgrade():
    for table in (
        "evaluation_model_attempts",
        "evaluation_test_evidence",
        "evaluation_result_nonces",
        "evaluation_reviews",
        "evaluation_intakes",
    ):
        if op.get_bind().execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated Evaluation evidence or reviews")
    if (
        op.get_bind()
        .execute(sa.text("SELECT 1 FROM evaluation_subjects WHERE blocked = true LIMIT 1"))
        .first()
    ):
        raise RuntimeError("Cannot downgrade populated Evaluation intake or tombstones")
    op.drop_column("evaluation_model_attempts", "gateway_configuration")
