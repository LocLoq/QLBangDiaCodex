from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class PenaltyCharge(Base, Timestamped):
    __tablename__ = "penalty_charges"
    id: Mapped[int] = mapped_column(primary_key=True)
    rental_term_id: Mapped[int] = mapped_column(ForeignKey("rental_terms.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
