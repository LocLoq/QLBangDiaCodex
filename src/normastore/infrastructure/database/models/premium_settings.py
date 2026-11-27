from decimal import Decimal

from sqlalchemy import Integer, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base


class PremiumSettings(Base):
    __tablename__ = "premium_settings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    merchandise_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    deposit_percent: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
