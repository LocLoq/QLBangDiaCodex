from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class Voucher(Base, Timestamped):
    __tablename__ = "vouchers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    percent_off: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount_off: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
