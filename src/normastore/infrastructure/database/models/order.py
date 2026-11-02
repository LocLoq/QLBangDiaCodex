from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.infrastructure.database.base import Base, Timestamped
from normastore.infrastructure.database.models.customer import Customer
from normastore.infrastructure.database.models.employee import Employee

if TYPE_CHECKING:
    from normastore.infrastructure.database.models.order_line import OrderLine


class Order(Base, Timestamped):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"))
    status: Mapped[str] = mapped_column(String(30), default="CONFIRMED")
    gross_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    deposit_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    customer: Mapped[Customer] = relationship()
    employee: Mapped[Employee] = relationship()
    lines: Mapped[list["OrderLine"]] = relationship(
        back_populates="order", cascade="all, delete-orphan"
    )
    __table_args__ = (Index("ix_order_customer_created", "customer_id", "created_at"),)
