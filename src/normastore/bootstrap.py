from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

from alembic.config import Config
from argon2 import PasswordHasher
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from alembic import command
from normastore.config import Settings
from normastore.domain.enums import RoleCode
from normastore.infrastructure.database import (
    CatalogItem,
    Customer,
    Employee,
    PhysicalCopy,
    Role,
    UserAccount,
    session_factory,
)


def ensure_database(settings: Settings) -> None:
    url = make_url(settings.database_url)
    # URL.set(database=None) intentionally leaves the component untouched; _replace creates
    # a true server-level MySQL URL so a first launch can create normastore_db.
    server_url = url._replace(database=None)
    engine = create_engine(server_url, future=True)
    database_name = url.database or "normastore_db"
    if not database_name.replace("_", "").isalnum():
        raise ValueError("Tên database chỉ được chứa chữ, số và dấu gạch dưới.")
    with engine.begin() as connection:
        connection.execute(
            text(
                f"CREATE DATABASE IF NOT EXISTS `{database_name}` "
                "CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci"
            )
        )
    engine.dispose()


def migrate_database(settings: Settings) -> None:
    """Apply the single source of schema changes before application services run."""
    ensure_database(settings)
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    config = Config(str(resource_root / "alembic.ini"))
    migration_root = resource_root / "alembic_migrations"
    if not migration_root.exists():
        migration_root = resource_root / "alembic"
    config.set_main_option("script_location", str(migration_root))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")


def seed_basics(session: Session) -> None:
    if session.query(Role).count():
        return
    roles = {code: Role(code=code, name=name) for code, name in [
        (RoleCode.ADMIN, "Quản trị viên"), (RoleCode.MANAGER, "Quản lý"), (RoleCode.STAFF, "Nhân viên"),
    ]}
    session.add_all(roles.values())
    hasher = PasswordHasher()
    employee = Employee(full_name="Quản trị viên NormaStore", phone="0000000000")
    session.add(employee)
    session.flush()
    session.add(UserAccount(employee_id=employee.id, role=roles[RoleCode.ADMIN], username="admin", password_hash=hasher.hash("admin123")))
    session.add_all([
        Customer(full_name="Nguyễn Minh Anh", phone="0900000001", email="anh@example.test"),
        Customer(full_name="Trần Gia Hân", phone="0900000002", email="han@example.test", reputation_score=92),
    ])
    movie = CatalogItem(item_type="MOVIE", title="Mẫu phim khởi động", overview="Dữ liệu minh họa NormaStore.", rental_price=Decimal("25000"), sale_price=Decimal("180000"), deposit_amount=Decimal("120000"), replacement_value=Decimal("180000"))
    session.add(movie)
    session.flush()
    session.add_all([
        PhysicalCopy(item_id=movie.id, barcode="DVD-DEMO-001", media_format="DVD"),
        PhysicalCopy(item_id=movie.id, barcode="DVD-DEMO-002", media_format="DVD"),
    ])


def bootstrap(settings: Settings):
    migrate_database(settings)
    factory = session_factory(settings.database_url)
    with factory() as session:
        seed_basics(session)
        session.commit()
    return factory
