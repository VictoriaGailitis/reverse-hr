"""Private practical environment data and fail-closed erasure tombstones."""

import sqlalchemy as sa
from alembic import op

revision = "0002_media"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "media_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.UniqueConstraint("request_id"),
    )
    op.create_table(
        "recordings",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("session_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("stage_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("format", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("consent_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("mime", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("size", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("expected_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("client_duration_ms", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("finalized_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("snapshot_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.UniqueConstraint("candidate_id", "session_id", "stage_id"),
        sa.UniqueConstraint("snapshot_id"),
    )
    op.create_index("ix_recordings_candidate_id", "recordings", ["candidate_id"])
    op.create_table(
        "recording_chunks",
        sa.Column(
            "recording_id",
            sa.String(length=36),
            sa.ForeignKey("recordings.id"),
            nullable=False,
            primary_key=True,
        ),
        sa.Column("number", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("data", sa.LargeBinary(), nullable=False, primary_key=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM media_subjects WHERE blocked = true LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated media environment or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM recordings LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated media environment or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM recording_chunks LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated media environment or restrictions")
    op.drop_table("recording_chunks")
    op.drop_table("recordings")
    op.drop_table("media_subjects")
    op.drop_table("media_nonces")
