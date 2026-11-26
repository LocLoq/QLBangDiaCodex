from __future__ import annotations

from decimal import Decimal

from normastore.domain.business_time import local_datetime
from normastore.domain.enums import RentalState, ReservationState, ReturnOutcome

RETURN_LABELS = {"Bình thường": ReturnOutcome.NORMAL, "Hư nhẹ": ReturnOutcome.LIGHT_DAMAGE,
                 "Hư nặng": ReturnOutcome.HEAVY_DAMAGE, "Mất đĩa": ReturnOutcome.LOST}
RENTAL_LABELS = {RentalState.ACTIVE: "Đang thuê", RentalState.RETURNED: "Đã trả",
                 RentalState.PURCHASED: "Đã mua", RentalState.LOST: "Đã mất",
                 RentalState.CANCELLED: "Đã hủy"}
RESERVATION_LABELS = {ReservationState.WAITING: "Đang chờ", ReservationState.HELD: "Đang giữ",
                      ReservationState.FULFILLED: "Đã nhận", ReservationState.EXPIRED: "Hết hạn",
                      ReservationState.CANCELLED: "Đã hủy"}
ORDER_LABELS = {"CONFIRMED": "Đã xác nhận", "PARTIALLY_PAID": "Chưa thanh toán đủ"}


def vnd(amount: Decimal | int | float | None, *, exact: bool = False) -> str:
    value = Decimal(amount or 0)
    if exact and value != value.to_integral_value():
        return f"{value:,.2f} đ".translate(str.maketrans(",.", ".,"))
    return f"{value:,.0f} đ".replace(",", ".")


def format_datetime(value) -> str:
    return local_datetime(value).strftime("%d/%m/%Y %H:%M") if value else "—"


def catalog_tooltip_text(item) -> str:
    """Format the common catalog tooltip without coupling it to a page."""
    return (
        f"{item.release_date or '—'} • Điểm {item.vote_average or '—'}\n"
        f"{item.overview or 'Chưa có tóm tắt.'}\n"
        f"Sẵn thuê: {item.rentable_copies} • Sẵn mua: {item.sellable_copies}\n"
        f"Giá gốc thuê: {vnd(item.rental_price)} • Giá gốc mua: {vnd(item.sale_price)}\n"
        "Giá thực tế tùy theo bản đĩa."
    )
