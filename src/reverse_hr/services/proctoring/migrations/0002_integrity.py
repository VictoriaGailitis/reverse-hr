"""Integrity evidence, human reviews and durable erasure fences."""

import sqlalchemy as sa
from alembic import op

revision = "0002_proctoring"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "integrity_tracks",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("session_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("stage_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("timeline_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("review_number", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("stage_id"),
    )
    op.create_index("ix_integrity_tracks_candidate_id", "integrity_tracks", ["candidate_id"])
    op.create_table(
        "proctor_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "proctor_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.UniqueConstraint("request_id"),
    )
    op.create_table(
        "integrity_reviews",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "track_id",
            sa.String(length=36),
            sa.ForeignKey("integrity_tracks.id"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("number", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("timeline_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("evidence_digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column("reviewer_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("outcome", sa.String(length=20), nullable=False, primary_key=False),
        sa.Column("reason", sa.String(length=2000), nullable=False, primary_key=False),
        sa.Column("evidence_ids", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("track_id", "number"),
    )
    op.create_index("ix_integrity_reviews_track_id", "integrity_reviews", ["track_id"])
    op.create_table(
        "proctor_streams",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "track_id",
            sa.String(length=36),
            sa.ForeignKey("integrity_tracks.id"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column(
            "client_started_at", sa.DateTime(timezone=True), nullable=False, primary_key=False
        ),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_index("ix_proctor_streams_track_id", "proctor_streams", ["track_id"])
    op.create_table(
        "proctor_events",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "track_id",
            sa.String(length=36),
            sa.ForeignKey("integrity_tracks.id"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("ordinal", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("source_key", sa.String(length=64), nullable=True),
        sa.UniqueConstraint("source_key"),
        sa.Column("source", sa.String(length=32), nullable=False, primary_key=False),
        sa.Column("kind", sa.String(length=64), nullable=False, primary_key=False),
        sa.Column(
            "stream_id",
            sa.String(length=36),
            sa.ForeignKey("proctor_streams.id"),
            nullable=True,
            primary_key=False,
        ),
        sa.Column("sequence", sa.Integer(), nullable=True, primary_key=False),
        sa.Column("client_time", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("elapsed_ms", sa.Integer(), nullable=True, primary_key=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("details", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("flags", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.UniqueConstraint("stream_id", "sequence"),
        sa.UniqueConstraint("track_id", "ordinal"),
    )
    op.create_index("ix_proctor_events_track_id", "proctor_events", ["track_id"])


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM integrity_tracks LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated proctoring evidence or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM integrity_reviews LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated proctoring evidence or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM proctor_streams LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated proctoring evidence or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM proctor_events LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated proctoring evidence or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM proctor_subjects WHERE blocked = true LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated proctoring evidence or restrictions")
    op.drop_table("proctor_events")
    op.drop_table("proctor_streams")
    op.drop_table("integrity_reviews")
    op.drop_table("proctor_subjects")
    op.drop_table("proctor_nonces")
    op.drop_table("integrity_tracks")
