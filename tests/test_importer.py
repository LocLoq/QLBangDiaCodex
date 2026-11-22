from datetime import date, timedelta
from decimal import Decimal
from functools import partial
from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from normastore.application._operations import _StoreOperations
from normastore.application.contracts import CatalogFilters, CheckoutLine, PaymentInput
from normastore.application.tmdb_import import as_date, certification, mock_prices, run_import
from normastore.domain.enums import ItemType, LineAction, PaymentMethod
from normastore.infrastructure.database.models import CatalogItem, Employee, Genre, Show
from normastore.infrastructure.database.unit_of_work import UnitOfWork

def test_mock_prices_follow_catalog_policy():
    rental, sale, replacement = mock_prices(12345)

    assert Decimal("15000") <= rental <= Decimal("40000")
    assert Decimal("100000") <= sale <= Decimal("500000")
    assert replacement == sale


def test_tmdb_metadata_helpers_accept_missing_or_invalid_values():
    assert as_date("2024-02-29").isoformat() == "2024-02-29"
    assert as_date("not-a-date") is None
    assert certification({"release_dates": {"results": [
        {"iso_3166_1": "US", "release_dates": [{"certification": "PG-13"}]},
    ]}}) == "PG-13"


def test_catalog_rejects_duplicate_tmdb_id_for_same_item_type(session):
    session.add_all([
        CatalogItem(item_type=ItemType.MOVIE, tmdb_id=991001, title="TMDB movie one"),
        CatalogItem(item_type=ItemType.MOVIE, tmdb_id=991001, title="TMDB movie duplicate"),
    ])

    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_tmdb_import_uses_checkpoints_with_fake_provider(session):
    movie_count = session.query(CatalogItem).filter(
        CatalogItem.item_type == ItemType.MOVIE, CatalogItem.tmdb_id.is_not(None)
    ).count()
    show_count = session.query(Show).filter(Show.tmdb_id.is_not(None)).count()
    payload = SimpleNamespace(tmdb_id=991197, title="Checkpoint movie", overview="", poster_path=None, vote_average=0)

    class FakeClient:
        closed = False

        def discover_movies(self, page):
            return [payload]

        def localized_movie_detail(self, tmdb_id):
            return {"title": payload.title, "genres": [], "reviews": {"results": []}}

        def discover_shows(self, page):
            return []

        def close(self):
            self.closed = True

    factory = sessionmaker(
        bind=session.connection(), expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    client = FakeClient()
    result = run_import(partial(UnitOfWork, factory), client, movie_count + 1, show_count)
    assert result == (movie_count + 1, show_count)
    assert client.closed
    assert session.query(CatalogItem).filter_by(tmdb_id=payload.tmdb_id).one().title == payload.title


def test_imported_series_genre_filters_and_sales_statistics(session):
    movie_count = session.query(CatalogItem).filter(
        CatalogItem.item_type == ItemType.MOVIE, CatalogItem.tmdb_id.is_not(None)
    ).count()
    show_count = session.query(Show).filter(Show.tmdb_id.is_not(None)).count()
    payload = SimpleNamespace(tmdb_id=991299, title="Series genre test", overview="", poster_path=None, vote_average=8)

    class FakeClient:
        def discover_movies(self, _page):
            return []

        def discover_shows(self, _page):
            return [payload]

        def localized_show_detail(self, _tmdb_id):
            return {"name": payload.title, "genres": [{"name": "Thể loại bộ nhập"}],
                    "seasons": [{"season_number": 1, "name": "Mùa 1"}], "reviews": {"results": []}}

        def localized_season_detail(self, _tmdb_id, _season):
            return {"episodes": [
                {"id": 991201, "episode_number": 1, "name": "Đã phát hành", "air_date": date.today().isoformat()},
                {"id": 991202, "episode_number": 2, "name": "Sắp phát hành", "air_date": (date.today() + timedelta(days=1)).isoformat()},
            ]}

        def close(self):
            pass

    factory = sessionmaker(bind=session.connection(), expire_on_commit=False, join_transaction_mode="create_savepoint")
    run_import(partial(UnitOfWork, factory), FakeClient(), movie_count, show_count + 1)
    session.expire_all()
    genre = session.query(Genre).filter_by(name="Thể loại bộ nhập").one()
    service = _StoreOperations(session)
    result = service.query_checkout_catalog(CatalogFilters(text=payload.title, genre_id=genre.id))
    assert result.total_items == 1 and result.items[0].show_id is not None
    assert result.items[0].total_copies > result.items[0].sellable_copies > 0
    first = session.query(CatalogItem).filter_by(tmdb_id=991201, item_type=ItemType.EPISODE).one()
    choice = service.checkout_copies(first.id, LineAction.BUY)[0]
    customer = service.list_customers()[0]
    actor = session.query(Employee.id).first()[0]
    lines = [CheckoutLine(choice.copy_id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    assert (genre.name, 1) in service.chart_report(date.today(), date.today(), genre_id=genre.id).genres
