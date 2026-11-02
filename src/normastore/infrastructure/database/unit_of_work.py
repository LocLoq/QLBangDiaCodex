from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker


class UnitOfWork:
    def __init__(self, factory: sessionmaker[Session]):
        self.factory = factory
        self.session: Session | None = None

    def __enter__(self) -> "UnitOfWork":
        self.session = self.factory()
        return self

    def commit(self) -> None:
        assert self.session is not None
        self.session.commit()

    def rollback(self) -> None:
        assert self.session is not None
        self.session.rollback()

    def __exit__(self, exc_type, exc, _tb) -> None:
        assert self.session is not None
        try:
            if exc_type:
                self.rollback()
            else:
                try:
                    self.commit()
                except Exception:
                    self.rollback()
                    raise
        finally:
            self.session.close()
