"""Private evidence journal and serialized authenticated chain."""

import sqlalchemy as sa
from alembic import op

revision = "0002_audit"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_chain_head",
        sa.Column("chain_id", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("signature", sa.String(128), nullable=False, primary_key=False),
    )
    op.create_table(
        "audit_entries",
        sa.Column("sequence", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("event_id", sa.String(36), nullable=False, primary_key=False, unique=True),
        sa.Column("producer", sa.String(50), nullable=False, primary_key=False),
        sa.Column("event_type", sa.String(120), nullable=False, primary_key=False),
        sa.Column("aggregate_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("aggregate_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("subjects", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("references", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("original_body", sa.Text(), nullable=True, primary_key=False),
        sa.Column("original_signature", sa.String(128), nullable=False, primary_key=False),
        sa.Column("proof_kind", sa.String(16), nullable=False, primary_key=False),
        sa.Column("content_digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("receipt_digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("projection_digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("previous_digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("chain_digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("chain_signature", sa.String(128), nullable=False, primary_key=False),
        sa.Column("delivery", sa.String(24), nullable=False, primary_key=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("erased", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("redaction_signature", sa.String(128), nullable=True, primary_key=False),
        sa.Column("redaction_reason", sa.String(16), nullable=True, primary_key=False),
        sa.Column("redacted_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
    )
    op.create_index("ix_audit_entries_aggregate_id", "audit_entries", ["aggregate_id"])
    op.create_index("ix_audit_entries_event_type", "audit_entries", ["event_type"])
    op.create_index("ix_audit_entries_expires_at", "audit_entries", ["expires_at"])
    op.create_index("ix_audit_entries_producer", "audit_entries", ["producer"])
    op.create_table(
        "audit_erased_subjects",
        sa.Column("subject_digest", sa.String(64), nullable=False, primary_key=True),
        sa.Column("request_digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "audit_nonces",
        sa.Column("owner", sa.String(50), nullable=False, primary_key=True),
        sa.Column("nonce", sa.String(36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "audit_streams",
        sa.Column("producer", sa.String(50), nullable=False, primary_key=True),
        sa.Column("aggregate_digest", sa.String(64), nullable=False, primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.execute(
        sa.text(
            "INSERT INTO audit_chain_head (chain_id, sequence, digest, signature) "
            "VALUES (1, 0, :digest, :signature)"
        ).bindparams(digest="0" * 64, signature="")
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM audit_chain_head WHERE sequence > 0 LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated Audit evidence")
    if bind.execute(sa.text("SELECT 1 FROM audit_streams LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated Audit evidence")
    if bind.execute(sa.text("SELECT 1 FROM audit_nonces LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated Audit evidence")
    if bind.execute(sa.text("SELECT 1 FROM audit_erased_subjects LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated Audit evidence")
    if bind.execute(sa.text("SELECT 1 FROM audit_entries LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated Audit evidence")
    op.drop_table("audit_streams")
    op.drop_table("audit_nonces")
    op.drop_table("audit_erased_subjects")
    op.drop_table("audit_entries")
    op.drop_table("audit_chain_head")
