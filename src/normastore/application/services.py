from __future__ import annotations

from dataclasses import replace
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Callable

from normastore.application._operations import _StoreOperations
from normastore.application.ai_search import SearchResponse, SearchResult
from normastore.application.contracts import (
    AccountView,
    ActiveRental,
    AuditQuery,
    AuditView,
    BusinessError,
    CatalogFilters,
    CatalogItemView,
    CatalogReview,
    CatalogRow,
    CheckoutLine,
    ComboSummary,
    CopyChoice,
    CustomerView,
    EmployeeSummary,
    GenreView,
    InventoryCopy,
    MockFixtureResult,
    MockSeedRequest,
    MockSeedResult,
    NotificationSummary,
    OrderDetailLine,
    OrderReceipt,
    OrderSummary,
    OrderView,
    PagedResult,
    PageRequest,
    PaymentInput,
    Quote,
    RecordView,
    ReservationView,
    ReturnableSale,
    ShiftView,
    ShowEpisodeSummary,
    ShowSummary,
    SortSpec,
    UpdateInventoryCopyRequest,
    VoucherSummary,
)
from normastore.application.recommendations import Recommendation
from normastore.application.reporting import OperationalReport
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    LineAction,
    PaymentMethod,
    ReturnOutcome,
    RoleCode,
)
from normastore.infrastructure.database.models import (
    Base,
    CatalogItem,
    Customer,
    Genre,
    Order,
    Shift,
    UserAccount,
)
from normastore.infrastructure.database.repositories.notifications import NotificationQueries
from normastore.jobs import process_notification_outbox


def _snapshot(value):
    """Materialize values consumed outside the unit of work."""
    if isinstance(value, UserAccount):
        return AccountView(
            value.id,
            value.employee_id,
            value.username,
            value.employee.full_name,
            value.role.code,
            value.role.name,
            value.must_change_password,
        )
    if isinstance(value, Shift):
        return ShiftView(
            value.id,
            value.employee_id,
            value.opened_at,
            value.closed_at,
            value.opening_cash,
            value.closing_cash,
        )
    if isinstance(value, Customer):
        return CustomerView(
            value.id,
            value.full_name,
            value.phone,
            value.email,
            value.address,
            value.reputation_score,
            value.email_opt_in,
            value.sms_opt_in,
        )
    if isinstance(value, Genre):
        return GenreView(value.id, value.name)
    if isinstance(value, CatalogItem):
        return CatalogItemView(
            value.id,
            value.item_type,
            value.title,
            value.overview,
            value.vote_average,
            value.rental_price,
            value.sale_price,
            value.deposit_amount,
            value.can_rent,
            value.can_sell,
        )
    if isinstance(value, Order):
        return OrderView(
            value.id,
            value.code,
            value.status,
            value.gross_total,
            value.discount_total,
            value.deposit_total,
        )
    if isinstance(value, Base):
        return RecordView(value.id)
    if isinstance(value, PagedResult):
        return replace(value, items=tuple(_snapshot(item) for item in value.items))
    if isinstance(value, list):
        return [_snapshot(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_snapshot(item) for item in value)
    return value


class StoreService:
    """Public application API; one unit of work is used for each call."""

    def __init__(self, uow_factory, integrations):
        self._uow_factory = uow_factory
        self._integrations = integrations

    def _execute(self, name, *args, **kwargs):
        with self._uow_factory() as uow:
            settings = self._integrations.settings
            operations = _StoreOperations(
                uow.session,
                self._integrations.gemini_api_key(),
                settings.gemini_embedding_model,
                settings.gemini_embedding_dimensions,
                settings.gemini_generation_model,
                self._integrations.gemini_factory,
            )
            return _snapshot(getattr(operations, name)(*args, **kwargs))

    def gemini_key_source(self) -> str:
        return self._integrations.gemini_key_source()

    def has_gemini_key(self) -> bool:
        return bool(self._integrations.gemini_api_key())

    def save_gemini_key(self, value: str) -> None:
        self._integrations.save_gemini_key(value)

    def delete_gemini_key(self) -> None:
        self._integrations.delete_gemini_key()

    def send_test_email(self) -> None:
        self._integrations.send_test_email()

    def export_order_pdf(self, order_id: int, actor_id: int, path, layout: str) -> None:
        receipt = self.order_receipt(order_id)
        self._integrations.export_receipt(receipt, path, layout)
        self.record_order_pdf_export(order_id, actor_id, layout, path.name)

    def process_notifications(self):
        with self._uow_factory() as uow:
            return process_notification_outbox(
                NotificationQueries(uow.session),
                self._integrations.email_sender(),
                self._integrations.send_sms,
            )

    def create_voucher_from_text(self, code: str, value: str, actor_id: int):
        text = value.strip().lower()
        percent = None if text.endswith("d") else Decimal(text)
        amount = Decimal(text[:-1]) if text.endswith("d") else None
        return self.create_voucher(code, actor_id, percent_off=percent, amount_off=amount)

    def run_mock_seed(
        self, request: MockSeedRequest, progress: Callable[[int, int], None] | None = None
    ) -> MockSeedResult:
        if request.end_on < request.start_on or (request.end_on - request.start_on).days > 30:
            raise BusinessError("Khoảng mock tối đa 31 ngày.")
        fixtures = self.ensure_mock_fixtures(request.actor_id)
        created = skipped = orders = 0
        total = (request.end_on - request.start_on).days + 1
        for offset in range(total):
            day = request.start_on + timedelta(days=offset)
            try:
                count = self.seed_mock_day(day, request.actor_id, request.volume_per_day)
            except Exception as exc:
                return MockSeedResult(
                    created,
                    skipped,
                    orders,
                    failed_on=day,
                    error=str(exc),
                    combos_created=fixtures.combos_created,
                    vouchers_created=fixtures.vouchers_created,
                    memberships_created=fixtures.memberships_created,
                )
            if count:
                created += 1
                orders += count
            else:
                skipped += 1
            if progress:
                progress(offset + 1, total)
        return MockSeedResult(
            created,
            skipped,
            orders,
            combos_created=fixtures.combos_created,
            vouchers_created=fixtures.vouchers_created,
            memberships_created=fixtures.memberships_created,
        )

    def authenticate(self, username: str, password: str) -> AccountView | None:
        return self._execute("authenticate", username, password)

    def change_password(self, account_id: int, current: str, new_password: str) -> None:
        return self._execute("change_password", account_id, current, new_password)

    def open_shift(self, employee_id: int, opening_cash: Decimal) -> ShiftView:
        return self._execute("open_shift", employee_id, opening_cash)

    def close_shift(self, shift_id: int, closing_cash: Decimal, actor_id: int) -> ShiftView:
        return self._execute("close_shift", shift_id, closing_cash, actor_id)

    def current_shift(self, employee_id: int) -> ShiftView | None:
        return self._execute("current_shift", employee_id)

    def list_employees(self) -> list[EmployeeSummary]:
        return self._execute("list_employees")

    def create_employee_account(
        self,
        full_name: str,
        phone: str,
        username: str,
        role_code: RoleCode,
        password: str,
        actor_id: int,
    ) -> RecordView:
        return self._execute(
            "create_employee_account", full_name, phone, username, role_code, password, actor_id
        )

    def add_customer(
        self, full_name: str, phone: str, email: str = "", actor_id: int | None = None
    ) -> CustomerView:
        return self._execute("add_customer", full_name, phone, email, actor_id)

    def adjust_reputation(
        self, customer_id: int, delta: int, reason: str, actor_id: int
    ) -> CustomerView:
        return self._execute("adjust_reputation", customer_id, delta, reason, actor_id)

    def query_customers(
        self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec()
    ) -> PagedResult[CustomerView]:
        return self._execute("query_customers", text, page_request, sort)

    def list_customers(self, text: str = "") -> list[CustomerView]:
        return self._execute("list_customers", text)

    def premium_active(self, customer_id: int, on_date: date | None = None) -> bool:
        return self._execute("premium_active", customer_id, on_date)

    def activate_premium(
        self,
        customer_id: int,
        days: int,
        employee_id: int | None = None,
        method: PaymentMethod = PaymentMethod.CASH,
    ) -> RecordView:
        return self._execute("activate_premium", customer_id, days, employee_id, method)

    def create_voucher(
        self,
        code: str,
        actor_id: int,
        percent_off: Decimal | None = None,
        amount_off: Decimal | None = None,
        starts_on: date | None = None,
        ends_on: date | None = None,
    ) -> RecordView:
        return self._execute(
            "create_voucher", code, actor_id, percent_off, amount_off, starts_on, ends_on
        )

    def list_vouchers(
        self, include_inactive: bool = True, today: date | None = None
    ) -> list[VoucherSummary]:
        return self._execute("list_vouchers", include_inactive, today)

    def create_fixed_combo(
        self, name: str, item_ids: list[int], discount_amount: Decimal, actor_id: int
    ) -> RecordView:
        return self._execute("create_fixed_combo", name, item_ids, discount_amount, actor_id)

    def create_show_episode_combo(
        self, name: str, show_id: int, required_count: int, discount_amount: Decimal, actor_id: int
    ) -> RecordView:
        return self._execute(
            "create_show_episode_combo", name, show_id, required_count, discount_amount, actor_id
        )

    def list_combos(self, include_inactive: bool = False) -> list[ComboSummary]:
        return self._execute("list_combos", include_inactive)

    def query_catalog(
        self,
        filters: CatalogFilters | None = None,
        page_request: PageRequest = PageRequest(page_size=48),
        sort: SortSpec = SortSpec(),
    ) -> PagedResult[CatalogRow]:
        return self._execute("query_catalog", filters, page_request, sort)

    def list_catalog(
        self,
        text: str = "",
        item_type: str = "",
        available_only: bool = False,
        page: int = 1,
        page_size: int = 48,
    ):
        return self._execute("list_catalog", text, item_type, available_only, page, page_size)

    def choose_checkout_copy(
        self, item_id: int, action: LineAction, excluded_copy_ids: set[int] | None = None
    ) -> CopyChoice | None:
        return self._execute("choose_checkout_copy", item_id, action, excluded_copy_ids)

    def list_genres(self) -> tuple[GenreView, ...]:
        return self._execute("list_genres")

    def catalog_item(self, item_id: int) -> CatalogItemView:
        return self._execute("catalog_item", item_id)

    def catalog_metadata(self, item_id: int) -> tuple[tuple[str, ...], tuple[CatalogReview, ...]]:
        return self._execute("catalog_metadata", item_id)

    def save_catalog_item(self, actor_id: int, **data) -> CatalogItemView:
        return self._execute("save_catalog_item", actor_id, **data)

    def list_shows(self) -> list[ShowSummary]:
        return self._execute("list_shows")

    def list_show_episodes(
        self, show_id: int, season_number: int | None = None
    ) -> list[ShowEpisodeSummary]:
        return self._execute("list_show_episodes", show_id, season_number)

    def create_show(
        self, title: str, overview: str = "", actor_id: int | None = None
    ) -> RecordView:
        return self._execute("create_show", title, overview, actor_id)

    def add_episodes_bulk(
        self,
        show_id: int,
        season_number: int,
        first_episode: int,
        last_episode: int,
        title_template: str = "Tập {number}",
        actor_id: int | None = None,
    ) -> list[CatalogItemView]:
        return self._execute(
            "add_episodes_bulk",
            show_id,
            season_number,
            first_episode,
            last_episode,
            title_template,
            actor_id,
        )

    def add_copy(
        self,
        item_id: int,
        barcode: str,
        media_format: str = "DVD",
        actor_id: int | None = None,
        can_rent: bool | None = None,
        can_sell: bool | None = None,
    ) -> RecordView:
        return self._execute(
            "add_copy", item_id, barcode, media_format, actor_id, can_rent, can_sell
        )

    def deposit_defaults(self) -> dict[str, Decimal]:
        return self._execute("deposit_defaults")

    def save_deposit_defaults(
        self, values: dict[str, Decimal], actor_id: int
    ) -> dict[str, Decimal]:
        return self._execute("save_deposit_defaults", values, actor_id)

    def apply_deposit_defaults_to_inventory(self, actor_id: int) -> int:
        return self._execute("apply_deposit_defaults_to_inventory", actor_id)

    def update_inventory_copy(
        self, copy_id: int, request: UpdateInventoryCopyRequest, actor_id: int
    ) -> RecordView:
        return self._execute("update_inventory_copy", copy_id, request, actor_id)

    def archive_items(self, item_ids: list[int], actor_id: int) -> int:
        return self._execute("archive_items", item_ids, actor_id)

    def bulk_update_catalog_prices(
        self,
        item_ids: list[int],
        actor_id: int,
        rental_price: Decimal | None = None,
        sale_price: Decimal | None = None,
        deposit_amount: Decimal | None = None,
    ) -> int:
        return self._execute(
            "bulk_update_catalog_prices",
            item_ids,
            actor_id,
            rental_price,
            sale_price,
            deposit_amount,
        )

    def quote(
        self,
        customer_id: int,
        lines: list[CheckoutLine],
        voucher_code: str | None = None,
        combo_ids: list[int] | None = None,
    ) -> Quote:
        return self._execute("quote", customer_id, lines, voucher_code, combo_ids)

    def checkout(
        self,
        customer_id: int,
        employee_id: int,
        shift_id: int | None,
        lines: list[CheckoutLine],
        payments: list[PaymentInput],
        voucher_code: str | None = None,
        combo_ids: list[int] | None = None,
        *,
        order_code: str | None = None,
    ) -> OrderView:
        return self._execute(
            "checkout",
            customer_id,
            employee_id,
            shift_id,
            lines,
            payments,
            voucher_code,
            combo_ids,
            order_code=order_code,
        )

    def query_active_rentals(
        self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("due", False)
    ) -> PagedResult[ActiveRental]:
        return self._execute("query_active_rentals", page_request, sort)

    def active_rentals(self) -> list[ActiveRental]:
        return self._execute("active_rentals")

    def query_orders(
        self,
        text: str = "",
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("created_at", True),
    ) -> PagedResult[OrderSummary]:
        return self._execute("query_orders", text, page_request, sort)

    def list_orders(self, text: str = "", limit: int = 200) -> list[OrderSummary]:
        return self._execute("list_orders", text, limit)

    def order_detail(self, order_id: int) -> tuple[OrderSummary, list[OrderDetailLine]]:
        return self._execute("order_detail", order_id)

    def order_receipt(self, order_id: int) -> OrderReceipt:
        return self._execute("order_receipt", order_id)

    def record_order_pdf_export(
        self, order_id: int, actor_id: int, layout: str, filename: str
    ) -> None:
        return self._execute("record_order_pdf_export", order_id, actor_id, layout, filename)

    def return_rentals(
        self,
        employee_id: int,
        customer_id: int,
        returns: list[tuple[int, ReturnOutcome, str]],
        payment: PaymentInput | None = None,
        today: date | None = None,
    ) -> Decimal:
        return self._execute("return_rentals", employee_id, customer_id, returns, payment, today)

    def extend_rental(self, rental_term_id: int, employee_id: int, days: int = 3) -> RecordView:
        return self._execute("extend_rental", rental_term_id, employee_id, days)

    def rental_to_sale(
        self, rental_term_id: int, employee_id: int, payment: PaymentInput
    ) -> OrderView:
        return self._execute("rental_to_sale", rental_term_id, employee_id, payment)

    def returnable_sales(self, today: date | None = None) -> list[ReturnableSale]:
        return self._execute("returnable_sales", today)

    def return_sale(
        self,
        sale_line_id: int,
        employee_id: int,
        today: date | None = None,
        condition: CopyCondition = CopyCondition.GOOD,
        deduction: Decimal = Decimal("0"),
        note: str = "",
    ) -> Decimal:
        return self._execute(
            "return_sale", sale_line_id, employee_id, today, condition, deduction, note
        )

    def query_inventory(
        self,
        status: CopyStatus | None = None,
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("title"),
    ) -> PagedResult[InventoryCopy]:
        return self._execute("query_inventory", status, page_request, sort)

    def list_inventory(
        self, status: CopyStatus | None = None, limit: int = 500
    ) -> list[InventoryCopy]:
        return self._execute("list_inventory", status, limit)

    def inspect_copy(
        self, copy_id: int, employee_id: int, target_status: CopyStatus, note: str = ""
    ) -> RecordView:
        return self._execute("inspect_copy", copy_id, employee_id, target_status, note)

    def reserve(
        self, customer_id: int, item_ids: list[int], actor_id: int | None = None
    ) -> list[RecordView]:
        return self._execute("reserve", customer_id, item_ids, actor_id)

    def query_reservations(
        self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created", True)
    ) -> PagedResult[ReservationView]:
        return self._execute("query_reservations", page_request, sort)

    def list_reservations(self) -> list[ReservationView]:
        return self._execute("list_reservations")

    def expire_reservation_holds(self, now: datetime | None = None) -> int:
        return self._execute("expire_reservation_holds", now)

    def allocate_waiting_reservations(self, item_id: int) -> int:
        return self._execute("allocate_waiting_reservations", item_id)

    def dashboard(self) -> dict[str, Decimal | int]:
        return self._execute("dashboard")

    def today_recommendations(self, limit: int = 8) -> list[Recommendation]:
        return self._execute("today_recommendations", limit)

    def customer_recommendations(self, customer_id: int, limit: int = 8) -> list[Recommendation]:
        return self._execute("customer_recommendations", customer_id, limit)

    def query_notifications(
        self,
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("scheduled", True),
    ) -> PagedResult[NotificationSummary]:
        return self._execute("query_notifications", page_request, sort)

    def list_notifications(self, limit: int = 300) -> list[NotificationSummary]:
        return self._execute("list_notifications", limit)

    def query_audit_logs(
        self,
        filters: AuditQuery = AuditQuery(),
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("created", True),
    ) -> PagedResult[AuditView]:
        return self._execute("query_audit_logs", filters, page_request, sort)

    def ensure_mock_fixtures(self, actor_id: int) -> MockFixtureResult:
        return self._execute("ensure_mock_fixtures", actor_id)

    def seed_mock_day(self, business_date: date, actor_id: int, volume_per_day: int = 250) -> int:
        return self._execute("seed_mock_day", business_date, actor_id, volume_per_day)

    def seed_mock_range(
        self, start_on: date, end_on: date, actor_id: int, volume_per_day: int = 250
    ) -> MockSeedResult:
        return self._execute("seed_mock_range", start_on, end_on, actor_id, volume_per_day)

    def search_by_description_response(self, description: str) -> SearchResponse:
        return self._execute("search_by_description_response", description)

    def search_by_description(self, description: str) -> list[SearchResult]:
        return self._execute("search_by_description", description)

    def operational_report(
        self, start_on: date | None = None, end_on: date | None = None
    ) -> OperationalReport:
        return self._execute("operational_report", start_on, end_on)
