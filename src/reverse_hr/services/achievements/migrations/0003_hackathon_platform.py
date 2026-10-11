"""Generalize the demo source without losing connections or custom names."""

import sqlalchemy as sa
from alembic import op

revision = "0003_hackathon_platform"
down_revision = "0002_achievements"
branch_labels = None
depends_on = None


def upgrade():
    sources = sa.table(
        "achievement_sources",
        sa.column("adapter", sa.String),
        sa.column("key", sa.String),
        sa.column("name", sa.String),
    )
    op.execute(
        sources.update()
        .where(sources.c.adapter == "demo-codenrock")
        .values(adapter="demo-hackathon-platform")
    )
    op.execute(
        sources.update()
        .where(sources.c.key == "demo-codenrock")
        .values(key="demo-hackathon-platform")
    )
    op.execute(
        sources.update()
        .where(sources.c.name == "Synthetic demo-codenrock")
        .values(name="Hackathon Platform")
    )


def downgrade():
    # Older service code expects the previous adapter identifier.
    sources = sa.table(
        "achievement_sources",
        sa.column("adapter", sa.String),
        sa.column("key", sa.String),
    )
    op.execute(
        sources.update()
        .where(sources.c.adapter == "demo-hackathon-platform")
        .values(adapter="demo-codenrock")
    )
    op.execute(
        sources.update()
        .where(sources.c.key == "demo-hackathon-platform")
        .values(key="demo-codenrock")
    )
