import runpy
from pathlib import Path

from normastore.config import Settings

BACKUP = runpy.run_path(Path(__file__).parents[1] / "scripts" / "backup_database.py")


def test_backup_command_uses_url_without_exposing_password():
    command = BACKUP["backup_command"](
        Settings(database_url="mysql+pymysql://root:secret@127.0.0.1:3307/normastore_db"),
        Path("mysqldump.exe"),
    )

    assert "secret" not in command
    assert "--password" in command
    assert "--port=3307" in command
    assert command[-1] == "normastore_db"
