from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from normastore.infrastructure.database.base import Base, Timestamped
from normastore.infrastructure.database.models.employee import Employee
from normastore.infrastructure.database.models.role import Role


class UserAccount(Base, Timestamped):
    __tablename__ = "user_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), unique=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    employee: Mapped[Employee] = relationship(back_populates="account")
    role: Mapped[Role] = relationship()
