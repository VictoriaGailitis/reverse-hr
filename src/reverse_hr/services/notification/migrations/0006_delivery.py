"""Verified email targets and leased consent-gated external delivery."""

import sqlalchemy as sa
from alembic import op

revision = "0006_notification"
down_revision = "0005_notification"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        "notification_notices",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.create_table(
        "notification_deliveries",
        sa.Column("delivery_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("subject", sa.String(36), nullable=False, primary_key=False),
        sa.Column("notice_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("challenge_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("target_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("category", sa.String(16), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("attempts", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("lease_token", sa.String(36), nullable=True, primary_key=False),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("provider_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("callback_sequence", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.UniqueConstraint("challenge_id"),
        sa.UniqueConstraint("notice_id", "target_version"),
    )
    op.create_index(
        "ix_notification_deliveries_notice_id", "notification_deliveries", ["notice_id"]
    )
    op.create_index("ix_notification_deliveries_subject", "notification_deliveries", ["subject"])
    op.create_table(
        "notification_delivery_attempts",
        sa.Column("delivery_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("number", sa.Integer(), nullable=False, primary_key=True),
        sa.Column("lease_token", sa.String(36), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
        sa.Column("at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "notification_delivery_callbacks",
        sa.Column("event_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("nonce", sa.String(36), nullable=False, primary_key=False),
        sa.Column("delivery_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("nonce"),
    )
    op.create_index(
        "ix_notification_delivery_callbacks_delivery_id",
        "notification_delivery_callbacks",
        ["delivery_id"],
    )
    op.create_table(
        "notification_email_challenges",
        sa.Column("challenge_id", sa.String(36), nullable=False, primary_key=True),
        sa.Column("subject", sa.String(36), nullable=False, primary_key=False),
        sa.Column("target_version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("salt", sa.String(64), nullable=False, primary_key=False),
        sa.Column("code_digest", sa.String(64), nullable=False, primary_key=False),
        sa.Column("ciphertext", sa.Text(), nullable=True, primary_key=False),
        sa.Column("consent_id", sa.String(36), nullable=False, primary_key=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("attempts", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(16), nullable=False, primary_key=False),
    )
    op.create_index(
        "ix_notification_email_challenges_subject", "notification_email_challenges", ["subject"]
    )
    op.create_table(
        "notification_email_preferences",
        sa.Column("subject", sa.String(36), nullable=False, primary_key=True),
        sa.Column("service_email", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("marketing_email", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("service_consent_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("marketing_consent_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column(
            "service_activated_at", sa.DateTime(timezone=True), nullable=True, primary_key=False
        ),
        sa.Column(
            "marketing_activated_at", sa.DateTime(timezone=True), nullable=True, primary_key=False
        ),
    )
    op.create_table(
        "notification_email_rate_windows",
        sa.Column("subject", sa.String(36), nullable=False, primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("next_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("used", sa.Integer(), nullable=False, primary_key=False),
    )
    op.create_table(
        "notification_email_targets",
        sa.Column("subject", sa.String(36), nullable=False, primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, primary_key=False),
        sa.Column("verified", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("challenge_id", sa.String(36), nullable=True, primary_key=False),
        sa.Column(
            "next_challenge_at", sa.DateTime(timezone=True), nullable=False, primary_key=False
        ),
        sa.Column("rate_started_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.Column("rate_count", sa.Integer(), nullable=False, primary_key=False),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM notification_deliveries LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated external notification history")
    if bind.execute(sa.text("SELECT 1 FROM notification_delivery_attempts LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated external notification history")
    if bind.execute(sa.text("SELECT 1 FROM notification_delivery_callbacks LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated external notification history")
    if bind.execute(sa.text("SELECT 1 FROM notification_email_challenges LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated external notification history")
    if bind.execute(sa.text("SELECT 1 FROM notification_email_preferences LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated external notification history")
    if bind.execute(sa.text("SELECT 1 FROM notification_email_rate_windows LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated external notification history")
    if bind.execute(sa.text("SELECT 1 FROM notification_email_targets LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated external notification history")
    # Preflight older revisions before nontransactional SQLite DDL removes current schema.
    for table in (
        "notification_notices",
        "notification_preferences",
        "outbox",
        "inbox",
        "idempotency_records",
    ):
        if bind.execute(sa.text(f"SELECT 1 FROM {table} LIMIT 1")).first():
            raise RuntimeError("Cannot downgrade populated notification data")
    if bind.execute(
        sa.text("SELECT 1 FROM notification_subjects WHERE blocked = true LIMIT 1")
    ).first():
        raise RuntimeError("Cannot downgrade populated notification data")
    op.drop_column("notification_notices", "created_at")
    op.drop_table("notification_deliveries")
    op.drop_table("notification_delivery_attempts")
    op.drop_table("notification_delivery_callbacks")
    op.drop_table("notification_email_challenges")
    op.drop_table("notification_email_preferences")
    op.drop_table("notification_email_rate_windows")
    op.drop_table("notification_email_targets")
