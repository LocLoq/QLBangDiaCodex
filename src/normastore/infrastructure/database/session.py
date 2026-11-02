from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from normastore.infrastructure.database.models import Base


def engine_from_url(url: str):
    return create_engine(url, pool_pre_ping=True, future=True)


def session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(engine_from_url(url), expire_on_commit=False, class_=Session)


def create_schema(url: str) -> None:
    # The database itself is created by bootstrap; this only owns NormaStore tables.
    Base.metadata.create_all(engine_from_url(url))
