from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, LargeBinary, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class ContentEmbedding(Base, Timestamped):
    __tablename__ = "content_embeddings"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(
        ForeignKey("catalog_items.id"), unique=True, nullable=False
    )
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
