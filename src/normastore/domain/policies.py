from __future__ import annotations

from datetime import date
from decimal import ROUND_UP, Decimal

from .enums import ReturnOutcome

THOUSAND = Decimal("1000")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def round_thousand(value: Decimal) -> Decimal:
    return (value / THOUSAND).quantize(Decimal("1"), rounding=ROUND_UP) * THOUSAND


def reputation_factor(score: int) -> tuple[Decimal, int, bool]:
    if score >= 90:
        return Decimal("0.85"), 2, False
    if score >= 70:
        return Decimal("1"), 0, False
    if score >= 50:
        return Decimal("1.25"), -1, False
    return Decimal("1.5"), -3, True


def effective_deposit(base: Decimal, premium: bool, reputation: int) -> Decimal:
    factor, _, _ = reputation_factor(reputation)
    return round_thousand(money(base) * (Decimal("0.70") if premium else Decimal("1")) * factor)


def late_days(due_date: date, today: date) -> int:
    return max(0, (today - due_date).days)


def late_fee(due_date: date, today: date, daily_rate: Decimal = Decimal("5000")) -> Decimal:
    return money(late_days(due_date, today) * daily_rate)


def damage_fee(replacement_value: Decimal, outcome: ReturnOutcome) -> Decimal:
    rate = {
        ReturnOutcome.NORMAL: Decimal("0"),
        ReturnOutcome.LIGHT_DAMAGE: Decimal("0.25"),
        ReturnOutcome.HEAVY_DAMAGE: Decimal("0.60"),
        ReturnOutcome.LOST: Decimal("1"),
    }[outcome]
    return money(replacement_value * rate)


def discount_total(subtotal: Decimal, combo_discount: Decimal, premium: bool, voucher_discount: Decimal) -> Decimal:
    after_combo = max(Decimal("0"), money(subtotal) - money(combo_discount))
    premium_discount = after_combo * Decimal("0.10") if premium else Decimal("0")
    raw = money(combo_discount) + money(premium_discount) + money(voucher_discount)
    return min(raw, money(subtotal) * Decimal("0.50"))


def sale_return_allowed(sold_on: date, returned_on: date) -> bool:
    return 0 <= (returned_on - sold_on).days <= 7

