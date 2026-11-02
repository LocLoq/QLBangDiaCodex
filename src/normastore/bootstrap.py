from __future__ import annotations

from normastore.config import Settings
from normastore.infrastructure.database.seed import seed_basics
from normastore.infrastructure.database.session import session_factory
from normastore.infrastructure.database.setup import migrate_database
from normastore.infrastructure.database.unit_of_work import UnitOfWork


def bootstrap(settings: Settings):
    migrate_database(settings)
    factory = session_factory(settings.database_url)
    with UnitOfWork(factory) as uow:
        seed_basics(uow.session)
    return factory


def build_application(factory, settings: Settings):
    """Wire the UI-facing service and presentation adapters."""
    from functools import partial

    from normastore.application.services import StoreService
    from normastore.infrastructure.integrations import Integrations

    integrations = Integrations(settings)
    return StoreService(partial(UnitOfWork, factory), integrations), integrations.poster_cache
