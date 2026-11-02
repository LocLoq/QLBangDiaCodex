from __future__ import annotations

from decimal import Decimal

from sqlalchemy import Boolean, Enum, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.domain.enums import CopyCondition, CopyStatus
from normastore.infrastructure.database.base import Base, Timestamped
from normastore.infrastructure.database.models.catalog_item import CatalogItem


class PhysicalCopy(Base, Timestamped):
    __tablename__ = "physical_copies"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), nullable=False)
    barcode: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    media_format: Mapped[str] = mapped_column(String(20), default="DVD", nullable=False)
    condition: Mapped[CopyCondition] = mapped_column(
        Enum(CopyCondition), default=CopyCondition.GOOD
    )
    status: Mapped[CopyStatus] = mapped_column(
        Enum(CopyStatus), default=CopyStatus.AVAILABLE, nullable=False
    )
    can_rent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_sell: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rental_price_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sale_price_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    deposit_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    item: Mapped[CatalogItem] = relationship(back_populates="copies")
    __table_args__ = (Index("ix_copy_item_status", "item_id", "status"),)
