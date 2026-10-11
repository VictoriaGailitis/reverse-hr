"""Private practical environment data and fail-closed erasure tombstones."""

import sqlalchemy as sa
from alembic import op

revision = "0002_whiteboard"
down_revision = "0001_transport"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "board_nonces",
        sa.Column("nonce", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
    )
    op.create_table(
        "board_subjects",
        sa.Column("subject", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("blocked", sa.Boolean(), nullable=False, primary_key=False),
        sa.Column("request_id", sa.String(length=36), nullable=True, primary_key=False),
        sa.UniqueConstraint("request_id"),
    )
    op.create_table(
        "boards",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column("candidate_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("session_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("stage_id", sa.String(length=36), nullable=False, primary_key=False),
        sa.Column("format", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("status", sa.String(length=16), nullable=False, primary_key=False),
        sa.Column("state", sa.JSON(), nullable=False, primary_key=False),
        sa.UniqueConstraint("candidate_id", "session_id", "stage_id"),
    )
    op.create_index("ix_boards_candidate_id", "boards", ["candidate_id"])
    op.create_table(
        "board_operations",
        sa.Column("operation_id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "board_id",
            sa.String(length=36),
            sa.ForeignKey("boards.id"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("command", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False, primary_key=False),
        sa.UniqueConstraint("board_id", "version"),
    )
    op.create_table(
        "board_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False, primary_key=True),
        sa.Column(
            "board_id",
            sa.String(length=36),
            sa.ForeignKey("boards.id"),
            nullable=False,
            primary_key=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False, primary_key=False),
        sa.Column("state", sa.JSON(), nullable=False, primary_key=False),
        sa.Column("digest", sa.String(length=64), nullable=False, primary_key=False),
        sa.UniqueConstraint("board_id"),
    )


def downgrade():
    bind = op.get_bind()
    if bind.execute(sa.text("SELECT 1 FROM board_subjects WHERE blocked = true LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated whiteboard environment or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM boards LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated whiteboard environment or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM board_operations LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated whiteboard environment or restrictions")
    if bind.execute(sa.text("SELECT 1 FROM board_snapshots LIMIT 1")).first():
        raise RuntimeError("Cannot downgrade populated whiteboard environment or restrictions")
    op.drop_table("board_snapshots")
    op.drop_table("board_operations")
    op.drop_table("boards")
    op.drop_table("board_subjects")
    op.drop_table("board_nonces")
