from datetime import datetime, timedelta, timezone

from normastore.application.recommendations import _as_utc


def test_as_utc_adds_utc_to_naive_mysql_timestamp():
    value = datetime(2026, 9, 16, 9, 30)

    assert _as_utc(value) == value.replace(tzinfo=timezone.utc)


def test_as_utc_converts_aware_timestamp():
    local = timezone(timedelta(hours=7))
    value = datetime(2026, 9, 16, 16, 30, tzinfo=local)

    assert _as_utc(value) == datetime(2026, 9, 16, 9, 30, tzinfo=timezone.utc)
