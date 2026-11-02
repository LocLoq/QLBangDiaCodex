from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base


class ItemGenre(Base):
    __tablename__ = "item_genres"
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), primary_key=True)
    genre_id: Mapped[int] = mapped_column(ForeignKey("genres.id"), primary_key=True)
