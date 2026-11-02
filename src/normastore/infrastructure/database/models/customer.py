from __future__ import annotations

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.infrastructure.database.base import Base, Timestamped


class Customer(Base, Timestamped):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    reputation_score: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
