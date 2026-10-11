"""Frozen schema for source-scoped achievements and demo exchanges."""

import sqlalchemy as sa
from alembic import op

revision = "0002_demo_ats"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "demo_ats_callbacks",
        sa.Column("callback_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("job_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("external_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("state", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("attempts", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("job_id", "sequence"),
    )
    op.create_index(
        "ix_demo_ats_callbacks_candidate_id", "demo_ats_callbacks", ["candidate_id"], unique=False
    )
    op.create_index(
        "ix_demo_ats_callbacks_actor_id", "demo_ats_callbacks", ["actor_id"], unique=False
    )
    op.create_index("ix_demo_ats_callbacks_job_id", "demo_ats_callbacks", ["job_id"], unique=False)
    op.create_table(
        "demo_ats_candidates",
        sa.Column("external_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("job_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("delivery_sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status_sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=24), nullable=False, primary_key=False),
        sa.Column("payload", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("candidate_id", "organization_id"),
    )
    op.create_index(
        "ix_demo_ats_candidates_candidate_id", "demo_ats_candidates", ["candidate_id"], unique=False
    )
    op.create_index(
        "ix_demo_ats_candidates_organization_id",
        "demo_ats_candidates",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        "ix_demo_ats_candidates_actor_id", "demo_ats_candidates", ["actor_id"], unique=False
    )
    op.create_table(
        "demo_ats_deliveries",
        sa.Column("job_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("actor_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("external_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("payload_digest", sa.String(length=64), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_demo_ats_deliveries_candidate_id", "demo_ats_deliveries", ["candidate_id"], unique=False
    )
    op.create_index(
        "ix_demo_ats_deliveries_actor_id", "demo_ats_deliveries", ["actor_id"], unique=False
    )
    op.create_index(
        "ix_demo_ats_deliveries_external_id", "demo_ats_deliveries", ["external_id"], unique=False
    )
    op.create_table(
        "demo_ats_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "demo_ats_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.UniqueConstraint("request_id"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM demo_ats_callbacks LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated demo-ats data")
    if bind.execute(sa.text("SELECT 1 FROM demo_ats_candidates LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated demo-ats data")
    if bind.execute(sa.text("SELECT 1 FROM demo_ats_deliveries LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated demo-ats data")
    if bind.execute(sa.text("SELECT 1 FROM demo_ats_nonces LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated demo-ats data")
    if bind.execute(
        sa.text("SELECT 1 FROM demo_ats_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated demo-ats data")
    op.drop_table("demo_ats_subjects")
    op.drop_table("demo_ats_nonces")
    op.drop_table("demo_ats_deliveries")
    op.drop_table("demo_ats_candidates")
    op.drop_table("demo_ats_callbacks")
