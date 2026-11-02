from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class ExternalReview(Base, Timestamped):
    __tablename__ = "external_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_items.id"))
    show_id: Mapped[int | None] = mapped_column(ForeignKey("shows.id"))
    tmdb_review_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    author: Mapped[str | None] = mapped_column(String(160))
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
