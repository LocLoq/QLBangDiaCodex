from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric, and_, or_
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.infrastructure.database.base import Base, Timestamped
from normastore.infrastructure.database.models.customer import Customer


class PremiumMembership(Base, Timestamped):
    __tablename__ = "premium_memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    cancelled_on: Mapped[date | None] = mapped_column(Date)
    price_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    customer: Mapped[Customer] = relationship()

    @classmethod
    def active_on(cls, day: date):
        return and_(
            cls.starts_on <= day,
            cls.ends_on >= day,
            or_(cls.cancelled_on.is_(None), cls.cancelled_on > day),
        )
