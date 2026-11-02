from __future__ import annotations

from decimal import Decimal

from argon2 import PasswordHasher
from sqlalchemy.orm import Session

from normastore.domain.enums import RoleCode
from normastore.infrastructure.database.models import (
    CatalogItem,
    Customer,
    Employee,
    PhysicalCopy,
    Role,
    UserAccount,
)


def seed_basics(session: Session) -> None:
    if session.query(Role).count():
        return
    roles = {
        code: Role(code=code, name=name)
        for code, name in [
            (RoleCode.ADMIN, "Quản trị viên"),
            (RoleCode.MANAGER, "Quản lý"),
            (RoleCode.STAFF, "Nhân viên"),
        ]
    }
    session.add_all(roles.values())
    hasher = PasswordHasher()
    employee = Employee(full_name="Quản trị viên NormaStore", phone="0000000000")
    session.add(employee)
    session.flush()
    session.add(
        UserAccount(
            employee_id=employee.id,
            role=roles[RoleCode.ADMIN],
            username="admin",
            password_hash=hasher.hash("admin123"),
        )
    )
    session.add_all(
        [
            Customer(full_name="Nguyễn Minh Anh", phone="0900000001", email="anh@example.test"),
            Customer(
                full_name="Trần Gia Hân",
                phone="0900000002",
                email="han@example.test",
                reputation_score=92,
            ),
        ]
    )
    movie = CatalogItem(
        item_type="MOVIE",
        title="Mẫu phim khởi động",
        overview="Dữ liệu minh họa NormaStore.",
        rental_price=Decimal("25000"),
        sale_price=Decimal("180000"),
        deposit_amount=Decimal("120000"),
        replacement_value=Decimal("180000"),
    )
    session.add(movie)
    session.flush()
    session.add_all(
        [
            PhysicalCopy(item_id=movie.id, barcode="DVD-DEMO-001", media_format="DVD"),
            PhysicalCopy(item_id=movie.id, barcode="DVD-DEMO-002", media_format="DVD"),
        ]
    )
