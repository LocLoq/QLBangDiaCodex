from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Date, Enum, ForeignKey, Index, Numeric
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.domain.enums import CopyCondition, RentalState
from normastore.infrastructure.database.base import Base
from normastore.infrastructure.database.models.order_line import OrderLine


class RentalTerm(Base):
    __tablename__ = "rental_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), unique=True, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[RentalState] = mapped_column(Enum(RentalState), default=RentalState.ACTIVE)
    late_daily_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=5000)
    issued_condition: Mapped[CopyCondition] = mapped_column(
        Enum(CopyCondition), default=CopyCondition.GOOD
    )
    returned_on: Mapped[date | None] = mapped_column(Date)
    line: Mapped[OrderLine] = relationship()
    __table_args__ = (Index("ix_rental_due_state", "due_date", "state"),)
