from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.domain.enums import LineAction
from normastore.infrastructure.database.base import Base
from normastore.infrastructure.database.models.order import Order
from normastore.infrastructure.database.models.physical_copy import PhysicalCopy


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    copy_id: Mapped[int | None] = mapped_column(ForeignKey("physical_copies.id"))
    action: Mapped[LineAction] = mapped_column(Enum(LineAction), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    source_rental_line_id: Mapped[int | None] = mapped_column(ForeignKey("order_lines.id"))
    order: Mapped[Order] = relationship(back_populates="lines", foreign_keys=[order_id])
    copy: Mapped[PhysicalCopy | None] = relationship(foreign_keys=[copy_id])
