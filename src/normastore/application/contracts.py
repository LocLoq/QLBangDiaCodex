from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    ItemType,
    LineAction,
    PaymentMethod,
    RentalState,
    ReservationState,
    RoleCode,
)


class BusinessError(ValueError):
    pass


@dataclass(frozen=True)
class AccountView:
    id: int
    employee_id: int
    username: str
    employee_name: str
    role_code: RoleCode
    role_name: str
    must_change_password: bool


@dataclass(frozen=True)
class ShiftView:
    id: int
    employee_id: int
    opened_at: datetime
    closed_at: datetime | None
    opening_cash: Decimal
    closing_cash: Decimal | None


@dataclass(frozen=True)
class CustomerView:
    id: int
    full_name: str
    phone: str
    email: str | None
    address: str | None
    reputation_score: int
    email_opt_in: bool
    sms_opt_in: bool


@dataclass(frozen=True)
class GenreView:
    id: int
    name: str


@dataclass(frozen=True)
class CatalogItemView:
    id: int
    item_type: ItemType
    title: str
    overview: str | None
    vote_average: Decimal | None
    rental_price: Decimal
    sale_price: Decimal
    deposit_amount: Decimal
    can_rent: bool
    can_sell: bool


@dataclass(frozen=True)
class OrderView:
    id: int
    code: str
    status: str
    gross_total: Decimal
    discount_total: Decimal
    deposit_total: Decimal


@dataclass(frozen=True)
class RecordView:
    id: int


@dataclass(frozen=True)
class CheckoutLine:
    copy_id: int
    action: LineAction
    due_date: date | None = None


@dataclass(frozen=True)
class PaymentInput:
    method: PaymentMethod
    amount: Decimal


@dataclass(frozen=True)
class PageRequest:
    page: int = 1
    page_size: int = 50


@dataclass(frozen=True)
class SortSpec:
    field: str = "title"
    descending: bool = False


@dataclass(frozen=True)
class PagedResult[T]:
    items: tuple[T, ...]
    page: int
    page_size: int
    total_items: int
    total_pages: int


@dataclass(frozen=True)
class CatalogFilters:
    text: str = ""
    item_type: str = ""
    genre_id: int | None = None
    year_from: int | None = None
    year_to: int | None = None
    rating_min: Decimal | None = None
    media_format: str = ""
    condition: CopyCondition | None = None
    copy_status: CopyStatus | None = None
    rental_price_min: Decimal | None = None
    rental_price_max: Decimal | None = None
    sale_price_min: Decimal | None = None
    sale_price_max: Decimal | None = None
    show_id: int | None = None
    season_number: int | None = None
    require_rentable: bool = False
    require_sellable: bool = False
    item_rentable: bool = False


@dataclass(frozen=True)
class CatalogRow:
    item_id: int
    item_type: ItemType
    title: str
    overview: str | None
    release_date: date | None
    vote_average: Decimal | None
    poster_path: str | None
    rental_price: Decimal
    sale_price: Decimal
    total_copies: int
    rentable_copies: int
    sellable_copies: int


@dataclass(frozen=True)
class CopyChoice:
    copy_id: int
    item_id: int
    barcode: str
    title: str
    action: LineAction
    unit_price: Decimal


@dataclass(frozen=True)
class Quote:
    gross: Decimal
    discount: Decimal
    deposit: Decimal
    total_due: Decimal
    line_prices: dict[int, Decimal]
    discount_sources: dict[str, Decimal]
    discount_source_codes: dict[str, str | None]


@dataclass(frozen=True)
class ActiveRental:
    term_id: int
    customer_id: int
    customer_name: str
    title: str
    barcode: str
    due_date: date


@dataclass(frozen=True)
class ReturnableSale:
    line_id: int
    customer_name: str
    title: str
    barcode: str
    sold_on: date
    expires_on: date


@dataclass(frozen=True)
class InventoryCopy:
    copy_id: int
    barcode: str
    title: str
    media_format: str
    condition: CopyCondition
    status: CopyStatus
    can_rent: bool
    can_sell: bool


@dataclass(frozen=True)
class UpdateInventoryCopyRequest:
    barcode: str
    media_format: str
    condition: CopyCondition
    can_rent: bool
    can_sell: bool
    status: CopyStatus
    rental_price_override: Decimal | None = None
    sale_price_override: Decimal | None = None
    deposit_override: Decimal | None = None
    note: str = ""


@dataclass(frozen=True)
class AuditView:
    audit_id: int
    created_at: datetime
    actor_name: str | None
    action: str
    entity: str
    entity_id: str
    detail: object | None


@dataclass(frozen=True)
class AuditQuery:
    text: str = ""
    action: str = ""
    actor_id: int | None = None


@dataclass(frozen=True)
class MockSeedResult:
    created_days: int
    skipped_days: int
    orders_created: int
    failed_on: date | None = None
    error: str | None = None
    combos_created: int = 0
    vouchers_created: int = 0
    memberships_created: int = 0


@dataclass(frozen=True)
class MockSeedRequest:
    start_on: date
    end_on: date
    actor_id: int
    volume_per_day: int = 250


@dataclass(frozen=True)
class MockFixtureResult:
    combos_created: int
    vouchers_created: int
    memberships_created: int


@dataclass(frozen=True)
class CatalogReview:
    author: str
    rating: Decimal | None
    content: str


@dataclass(frozen=True)
class ReservationView:
    reservation_id: int
    customer_name: str
    item_title: str
    state: ReservationState
    hold_until: datetime | None


@dataclass(frozen=True)
class ShowSummary:
    show_id: int
    title: str
    overview: str | None
    vote_average: Decimal | None
    season_count: int


@dataclass(frozen=True)
class ShowEpisodeSummary:
    item_id: int
    title: str
    season_number: int
    episode_number: int
    vote_average: Decimal | None
    rentable_copies: int
    sellable_copies: int


@dataclass(frozen=True)
class VoucherSummary:
    voucher_id: int
    code: str
    description: str
    active: bool
    starts_on: date | None
    ends_on: date | None
    effective_state: str


@dataclass(frozen=True)
class ComboSummary:
    combo_id: int
    name: str
    rule_type: str
    scope: str
    required_count: int | None
    discount_amount: Decimal
    active: bool


@dataclass(frozen=True)
class OrderSummary:
    order_id: int
    code: str
    customer_name: str
    employee_name: str
    created_at: datetime
    status: str
    total_due: Decimal


@dataclass(frozen=True)
class OrderDetailLine:
    title: str
    barcode: str | None
    action: LineAction
    unit_price: Decimal
    deposit: Decimal
    due_date: date | None
    rental_state: RentalState | None


@dataclass(frozen=True)
class ReceiptDiscount:
    source: str
    amount: Decimal
    source_code: str | None


@dataclass(frozen=True)
class ReceiptPayment:
    method: PaymentMethod
    category: str
    amount: Decimal
    created_at: datetime


@dataclass(frozen=True)
class OrderReceiptLine:
    title: str
    barcode: str | None
    action: LineAction
    unit_price: Decimal
    discount_amount: Decimal
    net_amount: Decimal
    deposit: Decimal
    due_date: date | None
    rental_state: str | None


@dataclass(frozen=True)
class OrderReceipt:
    order_id: int
    code: str
    created_at: datetime
    status: str
    customer_name: str
    customer_phone: str | None
    customer_email: str | None
    customer_address: str | None
    employee_name: str
    gross_total: Decimal
    discount_total: Decimal
    deposit_total: Decimal
    total_due: Decimal
    checkout_paid: Decimal
    balance_due: Decimal
    lines: tuple[OrderReceiptLine, ...]
    discounts: tuple[ReceiptDiscount, ...]
    payments: tuple[ReceiptPayment, ...]


@dataclass(frozen=True)
class EmployeeSummary:
    employee_id: int
    full_name: str
    phone: str | None
    active: bool
    username: str | None
    role_name: str | None


@dataclass(frozen=True)
class NotificationSummary:
    notification_id: int
    customer_name: str
    channel: str
    event: str
    scheduled_for: datetime
    status: str
    attempts: int
    error: str | None
