"""Run database upgrades with the same configuration and backup as application startup."""

from normastore.config import Settings
from normastore.infrastructure.database.setup import migrate_database


def main() -> None:
    migrate_database(Settings())


if __name__ == "__main__":
    main()
