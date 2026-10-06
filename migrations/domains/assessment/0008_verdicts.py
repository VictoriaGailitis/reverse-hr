"""Private signature-verified validation receipts (scoring remains disabled)."""

import sqlalchemy as sa
from alembic import op

revision = "0008_assessment"
down_revision = "0007_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "suite_validation_intakes",
        sa.Column("validation_id", sa.String(36), primary_key=True),
        sa.Column("suite_id", sa.String(36), sa.ForeignKey("test_suites.suite_id"), nullable=False),
        sa.Column("owner_id", sa.String(36), nullable=False),
        sa.Column("proof", sa.JSON(), nullable=False),
        sa.Column("proof_signature", sa.String(128), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_suite_validation_intakes_owner_id", "suite_validation_intakes", ["owner_id"]
    )
    op.create_index(
        "ix_suite_validation_intakes_suite_id", "suite_validation_intakes", ["suite_id"]
    )


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
    op.drop_table("suite_validation_intakes")
