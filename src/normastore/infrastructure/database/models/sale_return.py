from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class SaleReturn(Base, Timestamped):
    __tablename__ = "sale_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    returned_on: Mapped[date] = mapped_column(Date, nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)
