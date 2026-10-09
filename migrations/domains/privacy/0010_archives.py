"""Durable paginated immutable subject exports."""

import sqlalchemy as sa
from alembic import context, op

revision = "0010_privacy"
down_revision = "0009_privacy"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "privacy_archives",
        sa.Column("archive_id", sa.String(36), primary_key=True),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("manifest", sa.JSON(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("cursor", sa.String(16384)),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    for field in ("request_id", "candidate_id"):
        op.create_index("ix_privacy_archives_" + field, "privacy_archives", [field])
    op.create_table(
        "privacy_archive_pages",
        sa.Column("archive_id", sa.String(36), primary_key=True),
        sa.Column("number", sa.Integer(), primary_key=True),
        sa.Column("owner", sa.String(50), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("previous_digest", sa.String(64), nullable=False),
    )


def downgrade():
    bind = op.get_bind()
    tables = ["privacy_archives", "privacy_archive_pages"]
    if context.get_revision_argument() != "0009_privacy":
        tables += ["privacy_subject_requests", "privacy_request_history"]
    if context.get_revision_argument() not in {"0009_privacy", "0008_privacy"}:
        tables += ["company_result_grants", "deletion_requests", "backup_store_identity"]
    for table in tables:
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            if table == "deletion_requests":
                raise RuntimeError("Cannot downgrade a populated deletion ledger")
            raise RuntimeError("Cannot downgrade populated subject rights or Privacy ledger")
    if context.get_revision_argument() not in {
        "0009_privacy",
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
    op.drop_table("privacy_archive_pages")
    op.drop_table("privacy_archives")
