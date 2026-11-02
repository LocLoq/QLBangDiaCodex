from __future__ import annotations

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base


class ReturnLine(Base):
    __tablename__ = "return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("return_receipts.id"), nullable=False)
    rental_term_id: Mapped[int] = mapped_column(ForeignKey("rental_terms.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), default="NORMAL")
    note: Mapped[str | None] = mapped_column(Text)
