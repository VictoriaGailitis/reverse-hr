"""Optional immutable signed runtime attestation; allowlist remains operator config."""

import sqlalchemy as sa
from alembic import op

revision = "0009_assessment"
down_revision = "0008_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("suite_validation_intakes", sa.Column("attestation", sa.JSON(), nullable=True))
    op.add_column(
        "suite_validation_intakes",
        sa.Column("attestation_signature", sa.String(128), nullable=True),
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
    op.drop_column("suite_validation_intakes", "attestation_signature")
    op.drop_column("suite_validation_intakes", "attestation")
