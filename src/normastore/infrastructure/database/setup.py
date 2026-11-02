from __future__ import annotations

import sys
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from alembic import command
from normastore.config import Settings


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
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[4]))
    config = Config(str(resource_root / "alembic.ini"))
    migration_root = resource_root / "alembic_migrations"
    if not migration_root.exists():
        migration_root = resource_root / "alembic"
    config.set_main_option("script_location", str(migration_root))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
