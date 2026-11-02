from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.infrastructure.database.base import Base, Timestamped
from normastore.infrastructure.database.models.customer import Customer


class PremiumMembership(Base, Timestamped):
    __tablename__ = "premium_memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    price_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    customer: Mapped[Customer] = relationship()
