from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class DepositDefault(Base, Timestamped):
    """Default deposit by physical media format.

    Individual copies may still use ``deposit_override``.  Keeping these values
    in MySQL (rather than a local preference file) makes the policy durable and
    visible to every packaged installation pointed at the same store database.
    """

    __tablename__ = "deposit_defaults"
    media_format: Mapped[str] = mapped_column(String(20), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
