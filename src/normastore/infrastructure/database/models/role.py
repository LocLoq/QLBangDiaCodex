from __future__ import annotations

from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from normastore.domain.enums import RoleCode
from normastore.infrastructure.database.base import Base


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[RoleCode] = mapped_column(Enum(RoleCode), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
