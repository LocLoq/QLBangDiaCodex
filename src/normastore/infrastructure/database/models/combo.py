from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class Combo(Base, Timestamped):
    __tablename__ = "combos"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(40), default="FIXED")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    show_id: Mapped[int | None] = mapped_column(ForeignKey("shows.id"))
    required_count: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
