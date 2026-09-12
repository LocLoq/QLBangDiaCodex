import runpy
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.exc import IntegrityError

from normastore.domain.enums import ItemType
from normastore.infrastructure.database import CatalogItem

IMPORTER = runpy.run_path(Path(__file__).parents[1] / "scripts" / "import_tmdb.py")


def test_mock_prices_follow_catalog_policy():
    rental, sale, deposit, replacement = IMPORTER["mock_prices"](12345)

    assert Decimal("15000") <= rental <= Decimal("40000")
    assert Decimal("100000") <= sale <= Decimal("500000")
    assert replacement == sale
    assert replacement * Decimal("0.5") <= deposit <= replacement


def test_tmdb_metadata_helpers_accept_missing_or_invalid_values():
    assert IMPORTER["as_date"]("2024-02-29").isoformat() == "2024-02-29"
    assert IMPORTER["as_date"]("not-a-date") is None
    assert IMPORTER["certification"]({"release_dates": {"results": [
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
