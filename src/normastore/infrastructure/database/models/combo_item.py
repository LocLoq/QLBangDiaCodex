from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base


class ComboItem(Base):
    __tablename__ = "combo_items"
    combo_id: Mapped[int] = mapped_column(ForeignKey("combos.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), primary_key=True)
