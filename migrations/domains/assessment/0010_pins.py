"""Immutable private test-suite pins on plans and sessions; legacy plans remain unpinned."""

import sqlalchemy as sa
from alembic import op

revision = "0010_assessment"
down_revision = "0009_assessment"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("plan_versions", "assessment_sessions"):
        op.add_column(table, sa.Column("test_pins", sa.JSON(), nullable=True))
        op.add_column(table, sa.Column("test_pins_digest", sa.String(64), nullable=True))


def downgrade():
    connection = op.get_bind()
    for table in (
        "suite_validation_intakes",
        "test_suites",
        "assessment_stages",
        "assessment_sessions",
        "plan_versions",
        "content_revisions",
        "stage_nonces",
        "material_nonces",
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Cannot downgrade populated assessment content"
                if table == "content_revisions"
                else "Cannot downgrade populated assessment lifecycle or test suites"
            )
    if connection.execute(
        sa.text("SELECT 1 FROM assessment_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard assessment restrictions")
    for table in ("assessment_sessions", "plan_versions"):
        op.drop_column(table, "test_pins_digest")
        op.drop_column(table, "test_pins")
