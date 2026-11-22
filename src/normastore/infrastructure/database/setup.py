from __future__ import annotations

import sys
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from platformdirs import user_data_dir

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
    _backup_legacy_schema(settings)
    resource_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[4]))
    config = Config(str(resource_root / "alembic.ini"))
    migration_root = resource_root / "alembic_migrations"
    if not migration_root.exists():
        migration_root = resource_root / "alembic"
    config.set_main_option("script_location", str(migration_root))
    config.set_main_option("sqlalchemy.url", settings.database_url.replace("%", "%%"))
    config.attributes["backup_checked"] = True
    command.upgrade(config, "head")


def _backup_legacy_schema(settings: Settings) -> None:
    """Back up legacy data before irreversible schema revisions."""
    engine = create_engine(settings.database_url, future=True)
    try:
        with engine.connect() as connection:
            inspector = inspect(connection)
            legacy = inspector.has_table("shifts") or inspector.has_table("reputation_events")
            if inspector.has_table("catalog_items"):
                legacy |= "deposit_amount" in {column["name"] for column in inspector.get_columns("catalog_items")}
            if inspector.has_table("physical_copies"):
                legacy |= "deposit_override" in {column["name"] for column in inspector.get_columns("physical_copies")}
            if not legacy:
                return
            if inspector.has_table("alembic_version"):
                versions = set(connection.scalars(text("SELECT version_num FROM alembic_version")))
                if "20261121_08" in versions:
                    return
    finally:
        engine.dispose()
    executable = shutil.which("mysqldump")
    if not executable:
        candidates = sorted(Path("C:/laragon/bin/mysql").glob("*/bin/mysqldump.exe"), reverse=True)
        executable = str(candidates[0]) if candidates else None
    if not executable:
        raise RuntimeError("Không tìm thấy mysqldump để sao lưu trước khi nâng cấp database.")
    url = make_url(settings.database_url)
    directory = Path(user_data_dir("NormaStore")) / "backups"
    directory.mkdir(parents=True, exist_ok=True)
    output = directory / f"{url.database}-before-20261121_08-{datetime.now():%Y%m%d-%H%M%S-%f}.sql"
    temporary = output.with_suffix(".partial")
    args = [executable, f"--host={url.host or '127.0.0.1'}", f"--port={url.port or 3306}",
            f"--user={url.username or 'root'}", "--single-transaction", "--routines", "--events", url.database]
    environment = os.environ.copy()
    if url.password:
        environment["MYSQL_PWD"] = url.password
    else:
        environment.pop("MYSQL_PWD", None)
    try:
        with temporary.open("xb") as stream:
            subprocess.run(args, stdout=stream, check=True, env=environment, capture_output=False)
        temporary.replace(output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
