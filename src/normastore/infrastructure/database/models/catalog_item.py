from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import (
    Boolean,
    Date,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.domain.enums import ItemType
from normastore.infrastructure.database.base import Base, Timestamped
from normastore.infrastructure.database.models.season import Season
from normastore.infrastructure.database.models.show import Show

if TYPE_CHECKING:
    from normastore.infrastructure.database.models.physical_copy import PhysicalCopy


class CatalogItem(Base, Timestamped):
    __tablename__ = "catalog_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType), nullable=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    overview: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    vote_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    certification: Mapped[str | None] = mapped_column(String(30))
    poster_path: Mapped[str | None] = mapped_column(String(500))
    rental_price: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("25000"), nullable=False
    )
    sale_price: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("200000"), nullable=False
    )
    deposit_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("150000"), nullable=False
    )
    replacement_value: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), default=Decimal("250000"), nullable=False
    )
    can_rent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_sell: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_id: Mapped[int | None] = mapped_column(ForeignKey("shows.id"))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))
    episode_number: Mapped[int | None] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    show: Mapped[Show | None] = relationship()
    season: Mapped[Season | None] = relationship()
    copies: Mapped[list["PhysicalCopy"]] = relationship(
        back_populates="item", cascade="all, delete-orphan"
    )
    __table_args__ = (
        UniqueConstraint("item_type", "tmdb_id", name="uq_catalog_item_type_tmdb"),
        Index("ix_catalog_item_title", "title"),
        Index("ix_catalog_show_episode", "show_id", "season_id", "episode_number"),
    )
