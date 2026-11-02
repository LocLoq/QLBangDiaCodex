from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.infrastructure.database.base import Base, Timestamped

if TYPE_CHECKING:
    from normastore.infrastructure.database.models.user_account import UserAccount


class Employee(Base, Timestamped):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    account: Mapped["UserAccount | None"] = relationship(back_populates="employee", uselist=False)
