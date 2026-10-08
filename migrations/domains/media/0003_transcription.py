"""Immutable transcripts and explicit provider attempt history."""

import sqlalchemy as sa
from alembic import op

revision = "0003_media"
down_revision = "0002_media"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_transcripts",
        sa.Column("recording_id", sa.String(36), primary_key=True),
        sa.Column("transcript_id", sa.String(36), nullable=False, unique=True),
        sa.Column("attempt_id", sa.String(36), nullable=False, unique=True),
        sa.Column("recording_digest", sa.String(64), nullable=False),
        sa.Column("digest", sa.String(64), nullable=False),
        sa.Column("document", sa.JSON(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
    )
    op.create_table(
        "media_transcription_attempts",
        sa.Column("attempt_id", sa.String(36), primary_key=True),
        sa.Column("recording_id", sa.String(36), nullable=False),
        sa.Column("candidate_id", sa.String(36), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("recording_digest", sa.String(64), nullable=False),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("cost_microusd", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("recording_id", "number"),
    )
    op.create_index(
        "ix_media_transcription_attempts_recording_id",
        "media_transcription_attempts",
        ["recording_id"],
    )
    op.create_index(
        "ix_media_transcription_attempts_candidate_id",
        "media_transcription_attempts",
        ["candidate_id"],
    )


def downgrade():
    bind = op.get_bind()
    for table in (
        "media_transcripts",
        "media_transcription_attempts",
        "recordings",
        "recording_chunks",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated media environment or transcription")
    if bind.execute(sa.text("SELECT 1 FROM media_subjects WHERE blocked = true LIMIT 1")).first():
        raise RuntimeError("Cannot discard media restrictions")
    op.drop_table("media_transcription_attempts")
    op.drop_table("media_transcripts")
