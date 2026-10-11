from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column


class PoolColumns:
    subject_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    available_until: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class CaseColumns:
    case_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    kind: Mapped[str] = mapped_column(String(32), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int]


class ActionColumns:
    action_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(36), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    recipient_id: Mapped[str | None] = mapped_column(String(36), index=True)
    data: Mapped[dict] = mapped_column(JSON)
    version: Mapped[int]
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
