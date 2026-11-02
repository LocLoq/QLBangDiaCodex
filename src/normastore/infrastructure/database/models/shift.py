from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.infrastructure.database.base import Base, Timestamped, utcnow
from normastore.infrastructure.database.models.employee import Employee


class Shift(Base, Timestamped):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    employee: Mapped[Employee] = relationship()
