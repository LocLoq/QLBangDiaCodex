from decimal import Decimal

from sqlalchemy import Boolean, Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base


class PremiumPlan(Base):
    __tablename__ = "premium_plans"
    days: Mapped[int] = mapped_column(Integer, primary_key=True)
    price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
