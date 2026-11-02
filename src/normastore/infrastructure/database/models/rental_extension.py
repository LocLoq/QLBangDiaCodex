from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Numeric
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class RentalExtension(Base, Timestamped):
    __tablename__ = "rental_extensions"
    id: Mapped[int] = mapped_column(primary_key=True)
    rental_term_id: Mapped[int] = mapped_column(ForeignKey("rental_terms.id"), nullable=False)
    old_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
