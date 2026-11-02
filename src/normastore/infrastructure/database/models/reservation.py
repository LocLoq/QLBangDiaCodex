from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from normastore.domain.enums import ReservationState
from normastore.infrastructure.database.base import Base, Timestamped


class Reservation(Base, Timestamped):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), nullable=False)
    state: Mapped[ReservationState] = mapped_column(
        Enum(ReservationState), default=ReservationState.WAITING
    )
    hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allocated_copy_id: Mapped[int | None] = mapped_column(ForeignKey("physical_copies.id"))
    __table_args__ = (Index("ix_reservation_item_state_created", "item_id", "state", "created_at"),)
