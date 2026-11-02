from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.domain.enums import CopyStatus
from normastore.infrastructure.database.base import Base, utcnow


class CopyStatusHistory(Base):
    __tablename__ = "copy_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    copy_id: Mapped[int] = mapped_column(ForeignKey("physical_copies.id"), nullable=False)
    from_status: Mapped[CopyStatus | None] = mapped_column(Enum(CopyStatus))
    to_status: Mapped[CopyStatus] = mapped_column(Enum(CopyStatus), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
