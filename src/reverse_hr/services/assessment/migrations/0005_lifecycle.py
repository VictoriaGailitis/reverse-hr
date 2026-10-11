"""Server-controlled demo stages and immutable artifact references."""

import sqlalchemy as sa
from alembic import op

revision = "0005_assessment"
down_revision = "0004_assessment"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("assessment_sessions", sa.Column("current_stage_id", sa.String(36)))
    op.create_table(
        "assessment_stages",
        sa.Column("stage_id", sa.String(36), primary_key=True),
        sa.Column(
            "session_id",
            sa.String(36),
            sa.ForeignKey("assessment_sessions.session_id"),
            nullable=False,
        ),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("deadline", sa.DateTime(timezone=True)),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("workspace_id", sa.String(36)),
        sa.Column("snapshot_id", sa.String(36)),
        sa.Column("snapshot_version", sa.Integer()),
        sa.Column("digest", sa.String(64)),
    )
    op.create_index("ix_assessment_stages_session_id", "assessment_stages", ["session_id"])


def downgrade():
    connection = op.get_bind()
    for table in (
        "assessment_stages",
        "assessment_sessions",
        "plan_versions",
        "content_revisions",
        "stage_nonces",
    ):
        if connection.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                "Cannot downgrade populated assessment content"
                if table == "content_revisions"
                else "Cannot downgrade populated assessment lifecycle"
            )
    if connection.execute(
        sa.text("SELECT 1 FROM assessment_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot discard assessment restrictions")
    op.drop_table("assessment_stages")
    with op.batch_alter_table("assessment_sessions") as batch:
        batch.drop_column("current_stage_id")
