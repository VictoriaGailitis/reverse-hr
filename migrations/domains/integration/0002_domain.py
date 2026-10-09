"""Frozen schema for source-scoped achievements and demo exchanges."""

import sqlalchemy as sa
from alembic import op

revision = "0002_integration"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "ats_delivery_counters",
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("organization_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_table(
        "ats_status_receipts",
        sa.Column("receipt_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.UniqueConstraint("job_id", "sequence"),
    )
    op.create_index(
        "ix_ats_status_receipts_job_id", "ats_status_receipts", ["job_id"], unique=False
    )
    op.create_index(
        "ix_ats_status_receipts_candidate_id", "ats_status_receipts", ["candidate_id"], unique=False
    )
    op.create_table(
        "integration_jobs",
        sa.Column("job_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("connection_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("invitation_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("consent_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("attempts", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("lease_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("error_code", sa.String(length=32), nullable=True, primary_key=False),
        sa.Column("external_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.Column("external_status", sa.String(length=24), nullable=True, primary_key=False),
        sa.Column("status_sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=True, primary_key=False),
    )
    op.create_index(
        "ix_integration_jobs_organization_id", "integration_jobs", ["organization_id"], unique=False
    )
    op.create_index("ix_integration_jobs_actor_id", "integration_jobs", ["actor_id"], unique=False)
    op.create_index(
        "ix_integration_jobs_connection_id", "integration_jobs", ["connection_id"], unique=False
    )
    op.create_index(
        "ix_integration_jobs_candidate_id", "integration_jobs", ["candidate_id"], unique=False
    )
    op.create_table(
        "integration_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "integration_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.UniqueConstraint("request_id"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM ats_delivery_counters LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated integration data")
    if bind.execute(sa.text("SELECT 1 FROM ats_status_receipts LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated integration data")
    if bind.execute(sa.text("SELECT 1 FROM integration_jobs LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated integration data")
    if bind.execute(sa.text("SELECT 1 FROM integration_nonces LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated integration data")
    if bind.execute(
        sa.text("SELECT 1 FROM integration_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated integration data")
    op.drop_table("integration_subjects")
    op.drop_table("integration_nonces")
    op.drop_table("integration_jobs")
    op.drop_table("ats_status_receipts")
    op.drop_table("ats_delivery_counters")
