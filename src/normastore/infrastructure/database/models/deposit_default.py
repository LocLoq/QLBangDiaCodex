from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class DepositDefault(Base, Timestamped):
    """Store-wide deposit percentage, persisted under the PERCENT key."""

    __tablename__ = "deposit_defaults"
    media_format: Mapped[str] = mapped_column(String(20), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
