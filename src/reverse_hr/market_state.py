"""Local per-subject serialization shared by recruitment owners."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy import DateTime, String, select
from sqlalchemy.orm import Mapped, mapped_column


class NonceColumns:
    nonce: Mapped[str] = mapped_column(String(36), primary_key=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class SubjectColumns:
    subject: Mapped[str] = mapped_column(String(36), primary_key=True)
    blocked: Mapped[bool]
    request_id: Mapped[str | None] = mapped_column(String(36), unique=True)


def lock(session, model, subject, *, allow_blocked=False):
    if session.bind.dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(
        insert(model)
        .values(subject=str(subject), blocked=False)
        .on_conflict_do_nothing(index_elements=["subject"])
    )
    row = session.scalar(
        select(model)
        .where(model.subject == str(subject))
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if row.blocked and not allow_blocked:
        raise HTTPException(409)
    return row
