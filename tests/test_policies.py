from datetime import date
from decimal import Decimal

from normastore.domain.enums import ReturnOutcome
from normastore.domain.policies import damage_fee, effective_deposit, late_days, sale_return_allowed


def test_deposit_combines_premium_and_reputation() -> None:
    assert effective_deposit(Decimal("100000"), True, 90) == Decimal("60000")


def test_late_days_and_damage() -> None:
    assert late_days(date(2026, 9, 1), date(2026, 9, 3)) == 2
    assert damage_fee(Decimal("200000"), ReturnOutcome.HEAVY_DAMAGE) == Decimal("120000.00")


def test_sale_return_window() -> None:
    assert sale_return_allowed(date(2026, 9, 1), date(2026, 9, 8))
    assert not sale_return_allowed(date(2026, 9, 1), date(2026, 9, 9))

