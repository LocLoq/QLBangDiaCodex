from __future__ import annotations

from datetime import date
from decimal import ROUND_UP, Decimal

from .enums import ReturnOutcome

THOUSAND = Decimal("1000")


def money(value: Decimal | int | float | str) -> Decimal:
    return Decimal(str(value)).quantize(Decimal("0.01"))


def round_thousand(value: Decimal) -> Decimal:
    return (value / THOUSAND).quantize(Decimal("1"), rounding=ROUND_UP) * THOUSAND


def effective_deposit(base: Decimal, premium: bool) -> Decimal:
    return round_thousand(money(base) * (Decimal("0.70") if premium else Decimal("1")))


def effective_price(base: Decimal, item_mode: str, item_percent: Decimal,
                    copy_mode: str | None, copy_percent: Decimal | None,
                    condition_percent: Decimal, override: Decimal | None) -> Decimal:
    mode = copy_mode or ("DIRECT" if override is not None else item_mode)
    if mode == "DIRECT":
        return money(override if override is not None and (copy_mode == "DIRECT" or copy_mode is None) else base)
    if mode == "CONDITION":
        return money(Decimal(base) * Decimal(condition_percent) / Decimal("100"))
    if mode == "PERCENT":
        percent = copy_percent if copy_mode == "PERCENT" else item_percent
        return money(Decimal(base) * Decimal(percent) / Decimal("100"))
    raise ValueError("Chế độ giá không hợp lệ.")


def late_days(due_date: date, today: date) -> int:
    return max(0, (today - due_date).days)


def late_fee(due_date: date, today: date, daily_rate: Decimal = Decimal("5000")) -> Decimal:
    return money(late_days(due_date, today) * daily_rate)


def damage_fee(
    replacement_value: Decimal, outcome: ReturnOutcome, override: Decimal | None = None
) -> Decimal:
    if override is not None:
        if outcome not in (ReturnOutcome.LIGHT_DAMAGE, ReturnOutcome.HEAVY_DAMAGE):
            raise ValueError("Chỉ được nhập tiền phạt hư đĩa khi chọn Hư nhẹ hoặc Hư nặng.")
        if (not override.is_finite() or not 0 <= override < Decimal("1000000000000")
                or override != override.to_integral_value()):
            raise ValueError("Tiền phạt hư đĩa phải là số nguyên không âm và dưới 1.000 tỷ đồng.")
        return money(override)
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

