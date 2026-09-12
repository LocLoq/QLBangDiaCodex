"""Create a consistent MySQL backup before a migration or a large import.

Usage: python scripts/backup_database.py
Pass --mysqldump when Laragon is installed outside its default location.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from sqlalchemy.engine import make_url

from normastore.config import Settings

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def find_mysqldump(explicit: str | None) -> Path:
    if explicit:
        candidate = Path(explicit)
        if candidate.is_file():
            return candidate
    on_path = shutil.which("mysqldump")
    if on_path:
        return Path(on_path)
    laragon = Path("C:/laragon/bin/mysql")
    candidates = sorted(laragon.glob("*/bin/mysqldump.exe"), reverse=True)
    if candidates:
        return candidates[0]
    raise SystemExit("Không tìm thấy mysqldump. Hãy truyền --mysqldump <đường_dẫn>.")


def backup_command(settings: Settings, mysqldump: Path) -> list[str]:
    url = make_url(settings.database_url)
    if not url.database:
        raise ValueError("NORMASTORE_DATABASE_URL cần tên database để backup.")
    command = [
        str(mysqldump),
        f"--host={url.host or '127.0.0.1'}",
        f"--port={url.port or 3306}",
        f"--user={url.username or 'root'}",
        "--single-transaction",
        "--routines",
        "--events",
    ]
    if url.password:
        command.append("--password")
    command.append(url.database)
    return command


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mysqldump", help="Đường dẫn mysqldump.exe")
    parser.add_argument("--output", type=Path, help="File .sql đích")
    args = parser.parse_args()
    settings = Settings()
    output = args.output or Path("backups") / f"{make_url(settings.database_url).database}-{datetime.now():%Y%m%d-%H%M%S}.sql"
    output.parent.mkdir(parents=True, exist_ok=True)
    command = backup_command(settings, find_mysqldump(args.mysqldump))
    with output.open("wb") as stream:
        subprocess.run(command, stdout=stream, check=True)
    print(f"Đã tạo backup: {output}")


if __name__ == "__main__":
    main()
