from __future__ import annotations

from decimal import Decimal


def vnd(amount: Decimal | int | float | None) -> str:
    return f"{Decimal(amount or 0):,.0f} đ".replace(",", ".")


def catalog_tooltip_text(item) -> str:
    """Format the common catalog tooltip without coupling it to a page."""
    return (
        f"{item.release_date or '—'} • Rating {item.vote_average or '—'}\n"
        f"{item.overview or 'Chưa có tóm tắt.'}\n"
        f"Sẵn thuê: {item.rentable_copies} • Sẵn mua: {item.sellable_copies}\n"
        f"Thuê: {vnd(item.rental_price)} • Mua: {vnd(item.sale_price)}"
    )
