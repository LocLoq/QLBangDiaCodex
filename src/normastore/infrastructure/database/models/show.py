from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.infrastructure.database.base import Base, Timestamped

if TYPE_CHECKING:
    from normastore.infrastructure.database.models.season import Season


class Show(Base, Timestamped):
    __tablename__ = "shows"
    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_path: Mapped[str | None] = mapped_column(String(500))
    vote_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seasons: Mapped[list["Season"]] = relationship(
        back_populates="show", cascade="all, delete-orphan"
    )
