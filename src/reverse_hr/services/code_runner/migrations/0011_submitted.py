"""Submitted hidden-test work and physical cleanup obligations."""

import sqlalchemy as sa
from alembic import op

revision = "0011_submitted"
down_revision = "0010_queue"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "submitted_jobs",
        sa.Column("stage_id", sa.String(36), primary_key=True),
        *[
            sa.Column(name, sa.String(36), nullable=False)
            for name in ("candidate_id", "session_id", "workspace_id", "snapshot_id")
        ],
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("material", sa.JSON()),
        sa.Column("probe", sa.JSON()),
        sa.Column("failures", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True)),
        sa.Column("proof", sa.JSON()),
        sa.Column("signature", sa.String(128)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_submitted_jobs_candidate_id", "submitted_jobs", ["candidate_id"])
    op.create_table(
        "submitted_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        *[
            sa.Column(name, sa.String(36), nullable=False)
            for name in ("stage_id", "candidate_id", "node_id")
        ],
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("scope_id", sa.String(64), nullable=False),
        sa.Column("state", sa.String(16), nullable=False),
        sa.Column("capture", sa.JSON()),
        sa.Column("outcome", sa.JSON()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("stage_id", "ordinal"),
    )
    for name in ("stage_id", "candidate_id", "node_id"):
        op.create_index(f"ix_submitted_attempts_{name}", "submitted_attempts", [name])


def downgrade():
    bind = op.get_bind()
    for table in (
        "submitted_jobs",
        "submitted_attempts",
        "validation_work",
        "validation_verdicts",
        "validation_captures",
        "validation_attempts",
        "validation_batches",
        "runner_results",
        "runner_attempts",
        "runner_jobs",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError(
                {
                    "runner_jobs": "Cannot downgrade populated runner jobs",
                    "runner_results": "Cannot discard private execution results",
                    "validation_captures": "Cannot discard private validation captures",
                    "validation_verdicts": "Cannot discard signed validation verdicts",
                }.get(table, "Cannot discard runner work or cleanup obligations")
            )
    if bind.execute(sa.text("SELECT 1 FROM runner_subjects WHERE blocked = true LIMIT 1")).first():
        raise RuntimeError("Cannot discard runner restrictions")
    op.drop_table("submitted_attempts")
    op.drop_table("submitted_jobs")
