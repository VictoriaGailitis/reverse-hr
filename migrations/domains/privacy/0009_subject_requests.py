"""Subject rights requests, restriction state and immutable workflow history."""

import sqlalchemy as sa
from alembic import context, op

revision = "0009_privacy"
down_revision = "0008_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "privacy_subject_requests",
        sa.Column("request_id", sa.String(36), primary_key=True),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("domain", sa.String(50)),
        sa.Column("purpose", sa.String(50)),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("assignee_id", sa.String(36)),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("restriction_active", sa.Boolean(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
    )
    op.create_index(
        "ix_privacy_subject_requests_candidate_id", "privacy_subject_requests", ["candidate_id"]
    )
    op.create_table(
        "privacy_request_history",
        sa.Column("history_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("actor_id", sa.String(36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(32), nullable=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
    )
    for field in ("request_id", "candidate_id", "actor_id"):
        op.create_index("ix_privacy_request_history_" + field, "privacy_request_history", [field])


def downgrade():
    bind = op.get_bind()
    tables = ["privacy_subject_requests", "privacy_request_history"]
    if context.get_revision_argument() != "0008_privacy":
        tables += ["company_result_grants", "deletion_requests", "backup_store_identity"]
    # All requested-path guards before DDL, including SQLite.
    for table in tables:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            if table == "deletion_requests":
                raise RuntimeError("Cannot downgrade a populated deletion ledger")
            raise RuntimeError("Cannot downgrade populated subject rights or Privacy ledger")
    if context.get_revision_argument() not in {
        "0008_privacy",
        "0007_privacy",
        "0006_privacy",
        "0005_privacy",
        "0004_privacy",
    }:
        if bind.execute(
            sa.text("SELECT 1 FROM privacy_subjects WHERE blocked=true LIMIT 1")
        ).first():
            raise RuntimeError("Cannot discard deletion tombstones")
    op.drop_table("privacy_request_history")
    op.drop_table("privacy_subject_requests")
