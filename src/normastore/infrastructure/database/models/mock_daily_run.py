from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, utcnow


class MockDailyRun(Base):
    """Idempotency marker for an administrator-triggered demo-data run."""

    __tablename__ = "mock_daily_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    seed_version: Mapped[str] = mapped_column(String(40), nullable=False)
    stats: Mapped[dict | None] = mapped_column(JSON)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
