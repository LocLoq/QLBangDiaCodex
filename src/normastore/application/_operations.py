from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from random import Random
from secrets import token_hex
from zoneinfo import ZoneInfo


from argon2 import PasswordHasher
from sqlalchemy.exc import IntegrityError


from normastore.application.contracts import (
    ActiveRental,
    AuditQuery,
    AuditView,
    BusinessError,
    CatalogFilters,
    CatalogReview,
    CatalogRow,
    CheckoutLine,
    ComboSummary,
    CopyChoice,
    CreatedCopy,
    EmployeeSummary,
    InventoryCopy,
    MockFixtureResult,
    MockSeedResult,
    NotificationSummary,
    OrderDetailLine,
    OrderReceipt,
    OrderReceiptLine,
    OrderSummary,
    PageRequest,
    PagedResult,
    PaymentInput,
    Quote,
    RentalReturnInput,
    ReceiptDiscount,
    ReceiptPayment,
    ReservationView,
    ReturnableSale,
    ShowEpisodeSummary,
    ShowSummary,
    SortSpec,
    UpdateInventoryCopyRequest,
    VoucherSummary,
)
from normastore.application.ai_search import SearchResponse, SearchResult, search_response
from normastore.application.recommendations import Recommendation, for_customer
from normastore.application.recommendations import today as today_recommendations
from normastore.application.reporting import ChartReport, OperationalReport, operational_report
from normastore.domain.business_time import local_datetime
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    ItemType,
    LineAction,
    PaymentMethod,
    RentalState,
    ReservationState,
    ReturnOutcome,
    RoleCode,
)
from normastore.domain.policies import (
    damage_fee,
    effective_deposit,
    effective_price,
    late_fee,
    sale_return_allowed,
)
from normastore.infrastructure.database.models import (
    AuditLog,
    CatalogItem,
    Combo,
    ComboItem,
    CopyStatusHistory,
    Customer,
    DepositDefault,
    Employee,
    Genre,
    MockDailyRun,
    NotificationOutbox,
    Order,
    OrderDiscount,
    OrderLine,
    PaymentTransaction,
    PenaltyCharge,
    PhysicalCopy,
    PremiumMembership,
    RentalExtension,
    RentalTerm,
    Reservation,
    ReturnLine,
    ReturnReceipt,
    SaleReturn,
    Season,
    Show,
    UserAccount,
    Voucher,
)
from normastore.infrastructure.database.repositories.accounts import AccountsRepository
from normastore.infrastructure.database.repositories.dashboard import DashboardQueries
from normastore.infrastructure.database.repositories.mock import MockQueries
from normastore.infrastructure.database.repositories.customers import CustomerQueries
from normastore.infrastructure.database.repositories.catalog import CatalogQueries
from normastore.infrastructure.database.repositories.orders import OrderQueries
from normastore.infrastructure.database.repositories.inventory import InventoryQueries
from normastore.infrastructure.database.repositories.reservations import ReservationQueries
from normastore.infrastructure.database.repositories.notifications import NotificationQueries
from normastore.infrastructure.database.repositories.audit import AuditQueries
from normastore.infrastructure.database.repositories.promotions import PromotionsRepository
from normastore.infrastructure.database.repositories.recommendations import RecommendationRepository
from normastore.infrastructure.database.repositories.reporting import ReportingRepository
from normastore.infrastructure.database.repositories.search import SearchRepository
from normastore.infrastructure.external import GeminiSearch
from normastore.jobs import scheduled_reminders


class _StoreOperations:
    def __init__(
        self,
        session,
        gemini_api_key: str | None = None,
        gemini_embedding_model: str = "gemini-embedding-001",
        gemini_embedding_dimensions: int = 768,
        gemini_generation_model: str = "gemini-3.5-flash-lite",
        gemini_factory=GeminiSearch,
    ):
        self.reporting_repository = ReportingRepository(session)
        self.accounts = AccountsRepository(session)
        self.dashboard_queries = DashboardQueries(session)
        self.mock_queries = MockQueries(session)
        self.customers_queries = CustomerQueries(session)
        self.catalog_queries = CatalogQueries(session)
        self.orders_queries = OrderQueries(session)
        self.inventory_queries = InventoryQueries(session)
        self.reservations_queries = ReservationQueries(session)
        self.notifications_queries = NotificationQueries(session)
        self.audit_queries = AuditQueries(session)
        self.promotions = PromotionsRepository(session)
        self.recommendation_repository = RecommendationRepository(session)
        self.search_repository = SearchRepository(session)
        self.gemini_api_key = gemini_api_key
        self.gemini_embedding_model = gemini_embedding_model
        self.gemini_embedding_dimensions = gemini_embedding_dimensions
        self.gemini_generation_model = gemini_generation_model
        self.gemini_factory = gemini_factory
        self.password_hasher = PasswordHasher()
        self.reservation_state_changed = False

    def _audit(
        self,
        actor_id: int | None,
        action: str,
        entity: str,
        entity_id: int | str,
        detail: dict | str | None = None,
    ) -> None:
        self.accounts.add_audit(
            AuditLog(
                actor_id=actor_id,
                action=action,
                entity=entity,
                entity_id=str(entity_id),
                detail=detail,
            )
        )


    def authenticate(self, username: str, password: str) -> UserAccount | None:
        account = self.accounts.account_by_username(username.strip())
        if not account:
            self._audit(None, "LOGIN_FAILED", "UserAccount", username.strip() or "unknown", {"username": username.strip()})
            return None
        try:
            self.password_hasher.verify(account.password_hash, password)
        except Exception:
            self._audit(account.employee_id, "LOGIN_FAILED", "UserAccount", account.id, {"username": account.username})
            return None
        self._audit(account.employee_id, "LOGIN_SUCCESS", "UserAccount", account.id, {"username": account.username})
        return account

    def change_password(self, account_id: int, current: str, new_password: str) -> None:
        if len(new_password) < 8:
            raise BusinessError("Mật khẩu mới cần ít nhất 8 ký tự.")
        account = self.accounts.account(account_id)
        if not account:
            raise BusinessError("Không tìm thấy tài khoản.")
        try:
            self.password_hasher.verify(account.password_hash, current)
        except Exception as exc:
            raise BusinessError("Mật khẩu hiện tại không đúng.") from exc
        account.password_hash = self.password_hasher.hash(new_password)
        account.must_change_password = False
        self._audit(account.employee_id, "CHANGE_PASSWORD", "UserAccount", account.id)




    def list_employees(self) -> list[EmployeeSummary]:
        rows = self.accounts.employees()
        return [
            EmployeeSummary(
                employee_id=employee.id,
                full_name=employee.full_name,
                phone=employee.phone,
                active=employee.active,
                username=account.username if account else None,
                role_name=role.name if role else None,
            )
            for employee, account, role in rows
        ]

    def create_employee_account(self, full_name: str, phone: str, username: str, role_code: RoleCode, password: str, actor_id: int) -> Employee:
        self._require_manager(actor_id)
        if not full_name.strip() or not username.strip() or len(password) < 8:
            raise BusinessError("Cần tên, tài khoản và mật khẩu tối thiểu 8 ký tự.")
        if self.accounts.username_exists(username.strip()):
            raise BusinessError("Tên đăng nhập đã tồn tại.")
        role = self.accounts.role(role_code)
        if not role:
            raise BusinessError("Vai trò chưa được khởi tạo.")
        employee = Employee(full_name=full_name.strip(), phone=phone.strip() or None)
        self.accounts.save_employee(employee)
        self.accounts.add_account(UserAccount(employee_id=employee.id, role_id=role.id, username=username.strip(), password_hash=self.password_hasher.hash(password)))
        self._audit(actor_id, "CREATE_EMPLOYEE", "Employee", employee.id, {"username": username.strip(), "role": role_code.value})
        return employee

    def add_customer(self, full_name: str, phone: str, email: str = "", actor_id: int | None = None, *, address: str = "", email_opt_in: bool = True, sms_opt_in: bool = True) -> Customer:
        if not full_name.strip() or not phone.strip():
            raise BusinessError("Tên và số điện thoại là bắt buộc.")
        if self.customers_queries.customer_by_phone(phone.strip()):
            raise BusinessError("Số điện thoại đã tồn tại.")
        customer = Customer(full_name=full_name.strip(), phone=phone.strip(), email=email.strip() or None, address=address.strip() or None, email_opt_in=email_opt_in, sms_opt_in=sms_opt_in)
        self.customers_queries.save_customer(customer)
        self._audit(actor_id, "CREATE_CUSTOMER", "Customer", customer.id, {"phone": customer.phone})
        return customer

    def update_customer(
        self, customer_id: int, full_name: str, phone: str, email: str, actor_id: int,
        *, address: str, email_opt_in: bool, sms_opt_in: bool,
    ) -> Customer:
        customer = self.customers_queries.customer(customer_id)
        if customer is None:
            raise BusinessError("Không tìm thấy khách hàng.")
        full_name, phone, email, address = (
            full_name.strip(), phone.strip(), email.strip(), address.strip()
        )
        if not full_name or not phone:
            raise BusinessError("Tên và số điện thoại là bắt buộc.")
        if len(full_name) > 160 or len(phone) > 30 or len(email) > 255 or len(address) > 255:
            raise BusinessError("Họ tên tối đa 160 ký tự, số điện thoại 30, email và địa chỉ 255.")
        existing = self.customers_queries.customer_by_phone(phone)
        if existing is not None and existing.id != customer_id:
            raise BusinessError("Số điện thoại đã tồn tại.")
        customer.full_name = full_name
        customer.phone = phone
        customer.email = email or None
        customer.address = address or None
        customer.email_opt_in = email_opt_in
        customer.sms_opt_in = sms_opt_in
        self.customers_queries.save_customer(customer)
        self._audit(actor_id, "UPDATE_CUSTOMER", "Customer", customer.id)
        return customer

    def delete_customer(self, customer_id: int, actor_id: int) -> None:
        self._require_manager(actor_id)
        customer = self.customers_queries.customer(customer_id, lock=True)
        if customer is None:
            raise BusinessError("Không tìm thấy khách hàng.")
        try:
            self.customers_queries.delete_customer(customer)
        except IntegrityError as exc:
            if exc.orig.args and exc.orig.args[0] == 1451:
                raise BusinessError(
                    "Khách hàng đã có lịch sử nghiệp vụ nên không thể xóa."
                ) from exc
            raise
        self._audit(actor_id, "DELETE_CUSTOMER", "Customer", customer_id)


    def query_customers(self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec()) -> PagedResult[Customer]:
        return self.customers_queries.query_customers(text, page_request, sort)

    def list_customers(self, text: str = "") -> list[Customer]:
        return list(self.query_customers(text, PageRequest(1, 200)).items)

    def query_customers_with_premium(self, text: str = "", page_request: PageRequest = PageRequest()):
        return self.customers_queries.query_customers_with_premium(text, page_request, date.today())

    def premium_active(self, customer_id: int, on_date: date | None = None) -> bool:
        on_date = on_date or date.today()
        return self.customers_queries.premium_active(customer_id, on_date)

    def premium_until(self, customer_id: int, on_date: date | None = None) -> date | None:
        return self.customers_queries.premium_until(customer_id, on_date or date.today())

    def _active_memberships_for_edit(self, customer_id: int, actor_id: int, today: date):
        self._require_manager(actor_id)
        if self.customers_queries.customer(customer_id, lock=True) is None:
            raise BusinessError("Không tìm thấy khách hàng.")
        memberships = self.customers_queries.active_memberships(customer_id, today)
        if not memberships:
            raise BusinessError("Khách hàng không có Premium đang hiệu lực.")
        return memberships

    def set_premium_end_date(self, customer_id: int, ends_on: date, actor_id: int) -> None:
        today = date.today()
        if ends_on < today:
            raise BusinessError("Ngày hết hạn không được trước hôm nay.")
        current, *overlapping = self._active_memberships_for_edit(customer_id, actor_id, today)
        before = current.ends_on
        current.ends_on = ends_on
        for membership in overlapping:
            membership.ends_on = min(membership.ends_on, ends_on)
        self._audit(actor_id, "UPDATE_PREMIUM_END", "Customer", customer_id, {
            "before": before.isoformat(), "after": ends_on.isoformat(),
        })

    def cancel_premium(self, customer_id: int, actor_id: int) -> None:
        today = date.today()
        memberships = self._active_memberships_for_edit(customer_id, actor_id, today)
        for membership in memberships:
            membership.cancelled_on = today
        self._audit(actor_id, "CANCEL_PREMIUM", "Customer", customer_id, {
            "membership_ids": [membership.id for membership in memberships],
            "cancelled_on": today.isoformat(),
        })

    def activate_premium(
        self,
        customer_id: int,
        days: int,
        employee_id: int | None = None,
        method: PaymentMethod = PaymentMethod.CASH,
    ) -> PremiumMembership:
        prices = {30: Decimal("59000"), 90: Decimal("159000"), 365: Decimal("499000")}
        if days not in prices:
            raise BusinessError("Premium chỉ có kỳ hạn 30, 90 hoặc 365 ngày.")
        if not self.customers_queries.customer(customer_id, lock=True):
            raise BusinessError("Không tìm thấy khách hàng.")
        membership = PremiumMembership(
            customer_id=customer_id, starts_on=date.today(), ends_on=date.today() + timedelta(days=days - 1),
            price_paid=prices[days],
        )
        self.customers_queries.save_membership(
            membership, PaymentTransaction(
                customer_id=customer_id,
                employee_id=employee_id,
                method=method,
                category="PREMIUM",
                amount=prices[days],
            )
        )
        self._audit(employee_id, "ACTIVATE_PREMIUM", "PremiumMembership", membership.id, {
            "customer_id": customer_id, "days": days, "price": str(prices[days]),
        })
        return membership

    def create_voucher(
        self,
        code: str | None,
        actor_id: int,
        percent_off: Decimal | None = None,
        amount_off: Decimal | None = None,
        starts_on: date | None = None,
        ends_on: date | None = None,
    ) -> Voucher:
        self._require_manager(actor_id)
        if code is None:
            code = f"VC-{token_hex(6).upper()}"
            while self.promotions.voucher_exists(code):
                code = f"VC-{token_hex(6).upper()}"
        code = code.strip().upper()
        if not code:
            raise BusinessError("Mã voucher là bắt buộc.")
        if self.promotions.voucher_exists(code):
            raise BusinessError("Mã voucher đã tồn tại.")
        if bool(percent_off) == bool(amount_off):
            raise BusinessError("Voucher cần đúng một loại giảm: phần trăm hoặc số tiền.")
        if percent_off is not None and not Decimal("0") < percent_off <= Decimal("100"):
            raise BusinessError("Phần trăm giảm phải từ 0 đến 100.")
        if amount_off is not None and amount_off <= 0:
            raise BusinessError("Số tiền giảm phải lớn hơn 0.")
        if starts_on and ends_on and ends_on < starts_on:
            raise BusinessError("Ngày kết thúc không được trước ngày bắt đầu.")
        voucher = Voucher(
            code=code,
            percent_off=percent_off,
            amount_off=amount_off,
            starts_on=starts_on,
            ends_on=ends_on,
        )
        self.promotions.save_voucher(voucher)
        self._audit(actor_id, "CREATE_VOUCHER", "Voucher", voucher.id, {"code": voucher.code})
        return voucher

    def list_vouchers(self, include_inactive: bool = True, today: date | None = None) -> list[VoucherSummary]:
        today = today or date.today()
        vouchers = self.promotions.vouchers(include_inactive)

        def effective_state(voucher: Voucher) -> str:
            if not voucher.active:
                return "Đã tắt"
            if voucher.starts_on and voucher.starts_on > today:
                return "Chưa bắt đầu"
            if voucher.ends_on and voucher.ends_on < today:
                return "Hết hạn"
            return "Đang hiệu lực"

        return [
            VoucherSummary(
                voucher_id=voucher.id,
                code=voucher.code,
                description=(f"Giảm {voucher.percent_off}%" if voucher.percent_off else f"Giảm {Decimal(voucher.amount_off or 0):,.0f} đ"),
                active=voucher.active,
                starts_on=voucher.starts_on,
                ends_on=voucher.ends_on,
                effective_state=effective_state(voucher),
            )
            for voucher in vouchers
        ]

    def create_fixed_combo(self, name: str, item_ids: list[int], discount_amount: Decimal, actor_id: int) -> Combo:
        self._require_manager(actor_id)
        normalized_ids = sorted(set(item_ids))
        if not name.strip() or len(normalized_ids) < 2 or discount_amount <= 0:
            raise BusinessError("Combo cần tên, ít nhất 2 item và mức giảm lớn hơn 0.")
        found = self.promotions.available_item_ids(normalized_ids)
        if len(found) != len(normalized_ids):
            raise BusinessError("Combo có item không tồn tại hoặc đã lưu trữ.")
        combo = Combo(name=name.strip(), rule_type="FIXED", discount_amount=discount_amount)
        self.promotions.save_combo(combo, normalized_ids)
        self._audit(actor_id, "CREATE_COMBO", "Combo", combo.id, {"name": combo.name, "items": normalized_ids})
        return combo

    def create_show_episode_combo(self, name: str, show_id: int, required_count: int, discount_amount: Decimal, actor_id: int) -> Combo:
        self._require_manager(actor_id)
        if not name.strip() or required_count < 2 or discount_amount <= 0:
            raise BusinessError("Combo cần tên, từ 2 tập trở lên và mức giảm lớn hơn 0.")
        show = self.promotions.show(show_id)
        if not show or show.archived:
            raise BusinessError("Không tìm thấy bộ phim cho combo.")
        combo = Combo(
            name=name.strip(),
            rule_type="EPISODE_SHOW",
            show_id=show_id,
            required_count=required_count,
            discount_amount=discount_amount,
        )
        self.promotions.save_combo(combo)
        self._audit(actor_id, "CREATE_COMBO", "Combo", combo.id, {"name": combo.name, "show_id": show_id, "required_count": required_count})
        return combo

    def list_combos(self, include_inactive: bool = False) -> list[ComboSummary]:
        rows = self.promotions.combo_rows(include_inactive)
        return [
            ComboSummary(
                combo_id=combo.id,
                name=combo.name,
                rule_type=combo.rule_type,
                scope=(f"{int(item_count)} item cố định" if combo.rule_type == "FIXED" else (show_title or "Bộ phim đã xóa")),
                required_count=combo.required_count,
                discount_amount=Decimal(combo.discount_amount),
                active=combo.active,
            )
            for combo, show_title, item_count in rows
        ]

    def query_catalog(
        self,
        filters: CatalogFilters | None = None,
        page_request: PageRequest = PageRequest(page_size=48),
        sort: SortSpec = SortSpec(),
    ) -> PagedResult[CatalogRow]:
        return self.catalog_queries.query_catalog(filters, page_request, sort)

    def list_catalog(self, text: str = "", item_type: str = "", available_only: bool = False, page: int = 1, page_size: int = 48):
        return self.catalog_queries.list_catalog(text, item_type, available_only, page, page_size)

    def query_checkout_catalog(self, filters=None, page_request=PageRequest(page_size=48), sort=SortSpec(), customer_id=None):
        return self.catalog_queries.query_checkout_catalog(filters, page_request, sort, customer_id)

    def choose_checkout_copy(
        self,
        item_id: int,
        action: LineAction,
        excluded_copy_ids: set[int] | None = None,
    ) -> CopyChoice | None:
        choices = self.checkout_copies(item_id, action, excluded_copy_ids)
        return choices[0] if choices else None

    @staticmethod
    def _copy_price(copy: PhysicalCopy, action: LineAction) -> Decimal:
        prefix = "rental" if action == LineAction.RENT else "sale"
        item = copy.item
        return effective_price(
            getattr(item, f"{prefix}_price"), getattr(item, f"{prefix}_price_mode"),
            getattr(item, f"{prefix}_price_percent"), getattr(copy, f"{prefix}_price_mode"),
            getattr(copy, f"{prefix}_price_percent"), copy.condition_percent,
            getattr(copy, f"{prefix}_price_override"),
        )

    def checkout_copies(
        self, item_id: int, action: LineAction, excluded_copy_ids: set[int] | None = None,
        customer_id: int | None = None,
    ) -> list[CopyChoice]:
        if action not in (LineAction.RENT, LineAction.BUY):
            raise BusinessError("Loại dòng phiếu không hợp lệ.")
        self.expire_reservation_holds(item_id=item_id)
        self.allocate_waiting_reservations(item_id)
        choices = []
        for copy, item in self.catalog_queries.checkout_copies(item_id, action, excluded_copy_ids, customer_id=customer_id):
            price = self._copy_price(copy, action)
            choices.append(CopyChoice(copy.id, item.id, copy.barcode, item.title, action, Decimal(price), copy.media_format, copy.condition, copy.condition_percent, copy.aisle, copy.rack, copy.compartment))
        return choices

    def list_genres(self) -> tuple[Genre, ...]:
        return tuple(self.catalog_queries.fetch_list_genres_rows())

    def catalog_item(self, item_id: int) -> CatalogItem:
        item = self.catalog_queries.fetch_catalog_item_item(item_id)
        if not item:
            raise BusinessError("Không tìm thấy phim/tập phim.")
        return item

    def catalog_metadata(self, item_id: int) -> tuple[tuple[str, ...], tuple[CatalogReview, ...]]:
        item = self.catalog_item(item_id)
        genres = tuple(self.catalog_queries.fetch_catalog_metadata_genres(item))
        reviews = tuple(
            CatalogReview(
                review.author or "TMDB",
                Decimal(review.rating) if review.rating is not None else None,
                review.content,
            )
            for review in self.catalog_queries.reviews(item.id, item.show_id)
        )
        return genres, reviews

    def save_catalog_item(self, actor_id: int, **data) -> CatalogItem:
        self._require_manager(actor_id)
        genre_names = data.pop("genre_names", None)
        if genre_names is not None:
            if not isinstance(genre_names, (list, tuple)) or any(not isinstance(name, str) for name in genre_names):
                raise BusinessError("Danh sách thể loại không hợp lệ.")
            genre_names = [name.strip() for name in genre_names if name.strip()]
            if any(len(name) > 80 for name in genre_names):
                raise BusinessError("Tên thể loại không được dài quá 80 ký tự.")
        for key in ("rental_price_mode", "sale_price_mode"):
            if key in data and data[key] not in {"DIRECT", "CONDITION", "PERCENT"}:
                raise BusinessError("Chế độ giá không hợp lệ.")
        for key in ("rental_price", "sale_price", "rental_price_percent", "sale_price_percent"):
            if key in data and (not Decimal(data[key]).is_finite() or Decimal(data[key]) < 0):
                raise BusinessError("Giá và tỷ lệ phải là số không âm.")
        item_id = data.pop("id", None)
        if item_id:
            item = self.catalog_item(item_id)
            for key, value in data.items():
                if hasattr(item, key):
                    setattr(item, key, value)
        else:
            item = CatalogItem(**data)
            self.catalog_queries.add_catalog_item(item)
        self.catalog_queries.flush()
        if genre_names is not None:
            self.catalog_queries.set_item_genres(item.id, genre_names)
        self.catalog_queries.add_audit_log(AuditLog(actor_id=actor_id, action='UPDATE_CATALOG' if item_id else 'CREATE_CATALOG', entity='CatalogItem', entity_id=str(item.id), detail=item.title))
        return item

    def list_shows(self) -> list[ShowSummary]:
        return [
            ShowSummary(
                show_id=show.id,
                title=show.title,
                overview=show.overview,
                vote_average=Decimal(show.vote_average) if show.vote_average is not None else None,
                season_count=int(season_count),
                poster_path=show.poster_path,
            )
            for show, season_count in self.catalog_queries.fetch_list_shows_rows().all()
        ]

    def list_show_episodes(self, show_id: int, season_number: int | None = None) -> list[ShowEpisodeSummary]:
        if not self.catalog_queries.get_show(show_id):
            raise BusinessError("Không tìm thấy bộ phim.")
        return [
            ShowEpisodeSummary(
                item_id=item.id,
                title=item.title,
                season_number=number,
                episode_number=item.episode_number or 0,
                vote_average=Decimal(item.vote_average) if item.vote_average is not None else None,
                rentable_copies=int(available),
                sellable_copies=int(sellable_count),
            )
            for item, number, available, sellable_count in self.catalog_queries.show_episode_rows(show_id, season_number)
        ]

    def season_checkout_choices(
        self, show_id: int, season_number: int, action: LineAction,
        customer_id: int | None = None, excluded_copy_ids: set[int] | None = None,
        first_episode: int | None = None, last_episode: int | None = None,
    ) -> list[tuple[ShowEpisodeSummary, list[CopyChoice]]]:
        if season_number < 0 or action not in (LineAction.RENT, LineAction.BUY):
            raise BusinessError("Mùa hoặc loại giao dịch không hợp lệ.")
        if (first_episode is None) != (last_episode is None):
            raise BusinessError("Cần nhập cả tập đầu và tập cuối.")
        if first_episode is not None and (first_episode < 1 or last_episode < first_episode):
            raise BusinessError("Khoảng tập không hợp lệ.")
        episodes = self.list_show_episodes(show_id, season_number)
        if first_episode is not None:
            episodes = [episode for episode in episodes if first_episode <= episode.episode_number <= last_episode]
        if not episodes and first_episode is None:
            raise BusinessError("Mùa này chưa có tập phù hợp.")
        result = [(episode, self.checkout_copies(episode.item_id, action, excluded_copy_ids, customer_id)) for episode in episodes]
        return result

    def create_show(self, title: str, overview: str = "", actor_id: int | None = None) -> Show:
        if actor_id is None:
            raise BusinessError("Cần tài khoản quản lý để thêm bộ phim.")
        self._require_manager(actor_id)
        if not title.strip():
            raise BusinessError("Tên bộ phim là bắt buộc.")
        show = Show(title=title.strip(), overview=overview.strip() or None)
        self.catalog_queries.add_show(show)
        self.catalog_queries.flush()
        self.catalog_queries.add_audit_log(AuditLog(actor_id=actor_id, action='CREATE_SHOW', entity='Show', entity_id=str(show.id), detail=show.title))
        return show

    def set_show_poster(self, show_id: int, poster_path: str | None, actor_id: int) -> Show:
        self._require_manager(actor_id)
        show = self.catalog_queries.get_show(show_id)
        if not show:
            raise BusinessError("Không tìm thấy bộ phim.")
        if poster_path and len(poster_path) > 500:
            raise BusinessError("Đường dẫn ảnh không được dài quá 500 ký tự.")
        show.poster_path = poster_path or None
        self._audit(actor_id, "UPDATE_SHOW_POSTER", "Show", show.id, {"poster_path": show.poster_path})
        return show

    def add_episodes_bulk(
        self,
        show_id: int,
        season_number: int,
        first_episode: int,
        last_episode: int,
        title_template: str = "Tập {number}",
        actor_id: int | None = None,
    ) -> list[CatalogItem]:
        if actor_id is None:
            raise BusinessError("Cần tài khoản quản lý để thêm tập phim.")
        self._require_manager(actor_id)
        if season_number < 1 or first_episode < 1 or last_episode < first_episode:
            raise BusinessError("Mùa và khoảng tập không hợp lệ.")
        show = self.catalog_queries.get_show(show_id)
        if not show or show.archived:
            raise BusinessError("Không tìm thấy bộ phim.")
        season = self.catalog_queries.fetch_add_episodes_bulk_season(season_number, show_id)
        if not season:
            season = Season(show_id=show_id, season_number=season_number, name=f"Mùa {season_number}")
            self.catalog_queries.add_season(season)
            self.catalog_queries.flush()
        existing_numbers = set(
            self.catalog_queries.fetch_add_episodes_bulk_existing_numbers(season, show_id)
        )
        duplicates = [number for number in range(first_episode, last_episode + 1) if number in existing_numbers]
        if duplicates:
            raise BusinessError(f"Đã có tập {', '.join(map(str, duplicates))} của mùa này.")
        episodes = []
        for number in range(first_episode, last_episode + 1):
            try:
                episode_name = title_template.format(number=number)
            except (KeyError, ValueError) as exc:
                raise BusinessError("Mẫu tên tập chỉ dùng biến {number}.") from exc
            episode = CatalogItem(
                item_type=ItemType.EPISODE,
                title=f"{show.title} — T{season_number}E{number}: {episode_name}",
                overview=show.overview,
                show_id=show.id,
                season_id=season.id,
                episode_number=number,
                rental_price=Decimal("18000"),
                sale_price=Decimal("130000"),
                replacement_value=Decimal("130000"),
            )
            self.catalog_queries.add_catalog_item(episode)
            episodes.append(episode)
        self.catalog_queries.flush()
        self.catalog_queries.add_audit_log(AuditLog(actor_id=actor_id, action='BULK_CREATE_EPISODES', entity='Show', entity_id=str(show.id), detail=f'S{season_number} E{first_episode}-{last_episode}'))
        return episodes

    def add_copy(
        self,
        item_id: int,
        barcode: str | None = None,
        media_format: str = "DVD",
        actor_id: int | None = None,
        can_rent: bool | None = None,
        can_sell: bool | None = None,
        aisle: str = "",
        rack: str = "",
        compartment: str = "",
    ) -> PhysicalCopy:
        if actor_id is None:
            raise BusinessError("Cần tài khoản quản lý để nhập kho.")
        self._require_manager(actor_id)
        if any(len(value.strip()) > 80 for value in (aisle, rack, compartment)):
            raise BusinessError("Vị trí không được dài quá 80 ký tự.")
        item = self.catalog_item(item_id)
        if barcode is None:
            barcode = f"DIA-{token_hex(6).upper()}"
            while self.inventory_queries.fetch_add_copy_check(barcode):
                barcode = f"DIA-{token_hex(6).upper()}"
        if not barcode.strip():
            raise BusinessError("Barcode là bắt buộc.")
        if self.inventory_queries.fetch_add_copy_check(barcode):
            raise BusinessError("Barcode đã tồn tại.")
        rent_allowed = item.can_rent if can_rent is None else can_rent
        sell_allowed = item.can_sell if can_sell is None else can_sell
        if not rent_allowed and not sell_allowed:
            raise BusinessError("Bản đĩa phải cho phép thuê hoặc cho phép bán.")
        copy = PhysicalCopy(
            item_id=item.id,
            barcode=barcode.strip(),
            media_format=media_format,
            can_rent=rent_allowed,
            can_sell=sell_allowed,
            aisle=aisle.strip() or None,
            rack=rack.strip() or None,
            compartment=compartment.strip() or None,
        )
        self.inventory_queries.add_physical_copy(copy)
        self.inventory_queries.flush()
        self._status_history(copy, None, CopyStatus.AVAILABLE, "Nhập kho", actor_id)
        self._audit(actor_id, "ADD_COPY", "PhysicalCopy", copy.id, {
            "barcode": copy.barcode, "format": copy.media_format,
            "can_rent": copy.can_rent, "can_sell": copy.can_sell,
            "location": [copy.aisle, copy.rack, copy.compartment],
        })
        self.allocate_waiting_reservations(item.id)
        return copy

    def add_copies(
        self, item_id: int, quantity: int, media_format: str = "DVD",
        actor_id: int | None = None, can_rent: bool | None = None,
        can_sell: bool | None = None, aisle: str = "", rack: str = "", compartment: str = "",
    ) -> list[CreatedCopy]:
        if type(quantity) is not int or quantity < 1:
            raise BusinessError("Số lượng phải là số nguyên dương.")
        copies = [self.add_copy(item_id, None, media_format, actor_id, can_rent, can_sell,
                                aisle, rack, compartment) for _ in range(quantity)]
        return [CreatedCopy(copy.id, copy.barcode) for copy in copies]

    def deposit_percent(self) -> Decimal:
        return next((Decimal(row.amount) for row in self.inventory_queries.deposit_defaults() if row.media_format == "PERCENT"), Decimal("75"))

    def save_deposit_percent(self, value: Decimal, actor_id: int) -> Decimal:
        self._require_manager(actor_id)
        value = Decimal(value)
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("100"):
            raise BusinessError("Tỷ lệ cọc phải từ 0 đến 100%.")
        before = self.deposit_percent()
        row = next((row for row in self.inventory_queries.deposit_defaults() if row.media_format == "PERCENT"), None)
        if row is None:
            self.inventory_queries.add_deposit_default(DepositDefault(media_format="PERCENT", amount=value, updated_by=actor_id))
        else:
            row.amount, row.updated_by = value, actor_id
        self._audit(actor_id, "UPDATE_DEPOSIT_PERCENT", "DepositDefault", "PERCENT", {"before": str(before), "after": str(value)})
        return value




    def update_inventory_copy(
        self, copy_id: int, request: UpdateInventoryCopyRequest, actor_id: int
    ) -> PhysicalCopy:
        self._require_manager(actor_id)
        if any(value is not None and len(value.strip()) > 80 for value in (request.aisle, request.rack, request.compartment)):
            raise BusinessError("Vị trí không được dài quá 80 ký tự.")
        if not request.barcode.strip() or not (request.can_rent or request.can_sell):
            raise BusinessError("Cần barcode và ít nhất một quyền thuê/bán.")
        if any(value is not None and (not Decimal(value).is_finite() or value < 0) for value in (
            request.rental_price_override, request.sale_price_override,
        )):
            raise BusinessError("Giá override và tiền cọc không được âm.")
        if request.condition_percent is None or not Decimal(request.condition_percent).is_finite() or not Decimal("0") <= request.condition_percent <= Decimal("100"):
            raise BusinessError("Tình trạng phải từ 0 đến 100%.")
        for mode, percent, amount in ((request.rental_price_mode, request.rental_price_percent, request.rental_price_override), (request.sale_price_mode, request.sale_price_percent, request.sale_price_override)):
            if mode not in (None, "DIRECT", "CONDITION", "PERCENT"):
                raise BusinessError("Chế độ giá không hợp lệ.")
            if mode == "DIRECT" and amount is None:
                raise BusinessError("Giá nhập trực tiếp không được để trống.")
            if mode == "PERCENT" and (percent is None or not percent.is_finite() or percent < 0):
                raise BusinessError("Tỷ lệ giá phải là số không âm.")
        copy = self.inventory_queries.lock_copy(copy_id)
        if not copy:
            raise BusinessError("Không tìm thấy bản đĩa.")
        if request.barcode != copy.barcode:
            raise BusinessError("Mã đĩa do hệ thống quản lý, không được thay đổi.")
        if self.inventory_queries.fetch_update_inventory_copy_check(copy_id, request):
            raise BusinessError("Barcode đã tồn tại.")
        safe_statuses = {CopyStatus.AVAILABLE, CopyStatus.INSPECTION, CopyStatus.REPAIR, CopyStatus.LOST, CopyStatus.RETIRED}
        if request.status != copy.status and request.status not in safe_statuses:
            raise BusinessError("Trạng thái giao dịch chỉ được đổi qua nghiệp vụ thuê, bán hoặc giữ chỗ.")
        if copy.status not in safe_statuses and request.status != copy.status:
            raise BusinessError("Không thể ép đổi trạng thái của đĩa đang thuê, giữ chỗ hoặc đã bán.")
        if copy.status != request.status and not request.note.strip():
            raise BusinessError("Cần ghi chú khi đổi trạng thái kho.")
        before = {
            "barcode": copy.barcode, "format": copy.media_format, "condition": copy.condition.value,
            "status": copy.status.value, "can_rent": copy.can_rent, "can_sell": copy.can_sell,
            "location": [copy.aisle, copy.rack, copy.compartment],
        }
        old_status = copy.status
        copy.media_format = request.media_format
        copy.condition = request.condition
        copy.can_rent, copy.can_sell = request.can_rent, request.can_sell
        copy.rental_price_override = request.rental_price_override
        copy.sale_price_override = request.sale_price_override
        copy.condition_percent = request.condition_percent
        copy.rental_price_mode = request.rental_price_mode
        copy.sale_price_mode = request.sale_price_mode
        copy.rental_price_percent = request.rental_price_percent
        copy.sale_price_percent = request.sale_price_percent
        for name in ("aisle", "rack", "compartment"):
            value = getattr(request, name)
            if value is not None:
                setattr(copy, name, value.strip() or None)
        copy.status = request.status
        if old_status != copy.status:
            self._status_history(copy, old_status, copy.status, request.note.strip(), actor_id)
        if copy.status == CopyStatus.AVAILABLE:
            self.allocate_waiting_reservations(copy.item_id)
        self._audit(actor_id, "UPDATE_COPY", "PhysicalCopy", copy.id, {
            "before": before,
            "after": {
                "barcode": copy.barcode, "format": copy.media_format, "condition": copy.condition.value,
                "status": copy.status.value, "can_rent": copy.can_rent, "can_sell": copy.can_sell,
                "location": [copy.aisle, copy.rack, copy.compartment],
            },
            "note": request.note.strip() or None,
        })
        return copy

    def archive_items(self, item_ids: list[int], actor_id: int) -> int:
        self._require_manager(actor_id)
        items = list(self.inventory_queries.fetch_archive_items_items(item_ids))
        for item in items:
            item.archived = True
            self.inventory_queries.add_audit_log(AuditLog(actor_id=actor_id, action='ARCHIVE', entity='CatalogItem', entity_id=str(item.id), detail=None))
        return len(items)

    def bulk_update_catalog_prices(
        self,
        item_ids: list[int],
        actor_id: int,
        rental_price: Decimal | None = None,
        sale_price: Decimal | None = None,
    ) -> int:
        self._require_manager(actor_id)
        changes = {key: value for key, value in {"rental_price": rental_price, "sale_price": sale_price}.items() if value is not None}
        if not item_ids or not changes or any(value < 0 for value in changes.values()):
            raise BusinessError("Cần chọn item và nhập giá trị không âm để sửa hàng loạt.")
        items = list(self.inventory_queries.fetch_bulk_update_catalog_prices_items(item_ids))
        for item in items:
            for key, value in changes.items():
                setattr(item, key, value)
            self.inventory_queries.add_audit_log(AuditLog(actor_id=actor_id, action='BULK_PRICE_EDIT', entity='CatalogItem', entity_id=str(item.id), detail=','.join(changes)))
        return len(items)

    def _require_manager(self, employee_id: int) -> None:
        role_code = self.accounts.role_for_employee(employee_id)
        if role_code not in (RoleCode.ADMIN, RoleCode.MANAGER):
            raise BusinessError("Thao tác này cần quyền Quản lý hoặc Quản trị viên.")

    def quote(self, customer_id: int, lines: list[CheckoutLine], voucher_code: str | None = None, combo_ids: list[int] | None = None) -> Quote:
        if not lines:
            raise BusinessError("Phiếu chưa có bản đĩa nào.")
        if len(lines) != len({line.copy_id for line in lines}):
            raise BusinessError("Một bản đĩa không thể xuất hiện nhiều lần trong cùng phiếu.")
        self.allocate_for_checkout([line.copy_id for line in lines])
        customer = self.orders_queries.get_customer(customer_id)
        if not customer:
            raise BusinessError("Không tìm thấy khách hàng.")
        copies = list(self.orders_queries.fetch_quote_copies(lines))
        if len(copies) != len({line.copy_id for line in lines}):
            raise BusinessError("Có bản đĩa không tồn tại.")
        by_id = {copy.id: copy for copy in copies}
        gross = Decimal("0")
        deposit = Decimal("0")
        line_prices: dict[int, Decimal] = {}
        line_deposits: dict[int, Decimal] = {}
        premium = self.premium_active(customer_id)
        deposit_percent = self.deposit_percent()
        for line in lines:
            copy = by_id[line.copy_id]
            if copy.item.release_date and copy.item.release_date > date.today():
                raise BusinessError(f"{copy.item.title} chưa phát hành; hãy đặt trước.")
            held = copy.status == CopyStatus.HELD and self.reservations_queries.held_for_customer(copy.id, customer_id, datetime.now(timezone.utc))
            if copy.status != CopyStatus.AVAILABLE and not held:
                raise BusinessError(f"{copy.barcode} không còn sẵn sàng.")
            if line.action == LineAction.RENT:
                if not copy.can_rent or not copy.item.can_rent or not line.due_date:
                    raise BusinessError("Dòng thuê cần hạn trả và bản đĩa cho phép thuê.")
                price = self._copy_price(copy, LineAction.RENT)
                sale_price = self._copy_price(copy, LineAction.BUY)
                line_deposits[copy.id] = effective_deposit(Decimal(sale_price) * deposit_percent / Decimal("100"), premium)
                deposit += line_deposits[copy.id]
            elif line.action == LineAction.BUY:
                if not copy.can_sell or not copy.item.can_sell:
                    raise BusinessError("Bản đĩa không cho phép bán.")
                price = self._copy_price(copy, LineAction.BUY)
            else:
                raise BusinessError("Loại dòng phiếu không hợp lệ.")
            line_prices[copy.id] = Decimal(price)
            gross += Decimal(price)
        selected_item_ids = {copy.item_id for copy in copies}
        discount_cap = (gross * Decimal("0.50")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        discovery_by_copy = {}
        discovery_discount = Decimal("0")
        today = date.today()
        for line in lines:
            item = by_id[line.copy_id].item
            if (item.discovery_discount_active and item.discovery_discount_percent
                    and (item.discovery_discount_starts is None or item.discovery_discount_starts <= today)
                    and (item.discovery_discount_ends is None or item.discovery_discount_ends >= today)):
                amount = (line_prices[line.copy_id] * Decimal(item.discovery_discount_percent) / Decimal("100")).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                amount = min(amount, discount_cap - discovery_discount)
                discovery_by_copy[line.copy_id] = amount
                discovery_discount += amount
        combo_discount = Decimal("0")
        applied_combo_ids: list[int] = []
        for combo in self.promotions.active_combos(combo_ids or []):
            if combo.rule_type == "FIXED":
                required_ids = set(self.promotions.combo_item_ids(combo.id))
                applicable = bool(required_ids and required_ids.issubset(selected_item_ids))
            else:
                applicable = sum(copy.item.item_type == ItemType.EPISODE and copy.item.show_id == combo.show_id for copy in copies) >= (combo.required_count or 0)
            if applicable:
                combo_discount += Decimal(combo.discount_amount)
                applied_combo_ids.append(combo.id)
        combo_discount = min(combo_discount, discount_cap - discovery_discount)
        premium_discount = (gross - discovery_discount - combo_discount) * Decimal("0.10") if premium else Decimal("0")
        premium_discount = min(premium_discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), discount_cap - discovery_discount - combo_discount)
        voucher_discount = Decimal("0")
        if voucher_code:
            voucher = self.promotions.active_voucher(voucher_code.strip().upper())
            if not voucher:
                raise BusinessError("Voucher không hợp lệ.")
            today = date.today()
            if (voucher.starts_on and voucher.starts_on > today) or (voucher.ends_on and voucher.ends_on < today):
                raise BusinessError("Voucher chưa có hiệu lực hoặc đã hết hạn.")
            if voucher.percent_off:
                voucher_discount = (gross - discovery_discount - combo_discount - premium_discount) * Decimal(voucher.percent_off) / Decimal("100")
            elif voucher.amount_off:
                voucher_discount = Decimal(voucher.amount_off)
        voucher_discount = min(voucher_discount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP), discount_cap - discovery_discount - combo_discount - premium_discount)
        discount = discovery_discount + combo_discount + premium_discount + voucher_discount
        sources = {source: value for source, value in {"DISCOVERY": discovery_discount, "COMBO": combo_discount, "PREMIUM": premium_discount, "VOUCHER": voucher_discount}.items() if value}
        source_codes = {
            "COMBO": ",".join(map(str, applied_combo_ids)) or None,
            "VOUCHER": voucher_code.strip().upper() if voucher_code and voucher_discount else None,
            "PREMIUM": None,
            "DISCOVERY": None,
        }
        line_discounts = {line.copy_id: discovery_by_copy.get(line.copy_id, Decimal("0")) for line in lines}
        remaining_discount = discount - discovery_discount
        remaining_value = gross - discovery_discount
        for line in lines:
            capacity = line_prices[line.copy_id] - line_discounts[line.copy_id]
            share = (remaining_discount * capacity / remaining_value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP) if remaining_value else Decimal("0")
            share = min(share, capacity, remaining_discount)
            line_discounts[line.copy_id] += share
            remaining_discount -= share
            remaining_value -= capacity
        return Quote(gross, discount, deposit, gross - discount + deposit, line_prices, sources, source_codes, line_deposits, line_discounts)

    def checkout(
        self,
        customer_id: int,
        employee_id: int,
        lines: list[CheckoutLine],
        payments: list[PaymentInput],
        voucher_code: str | None = None,
        combo_ids: list[int] | None = None,
        *,
        order_code: str | None = None,
        expected_quote: Quote | None = None,
    ) -> Order:
        if any(Decimal(payment.amount) < 0 for payment in payments):
            raise BusinessError("Khoản thanh toán không được âm.")
        self.allocate_for_checkout([line.copy_id for line in lines])
        locked = list(self.orders_queries.fetch_checkout_locked(lines))
        by_id = {copy.id: copy for copy in locked}
        held_reservations = {}
        for copy in locked:
            if copy.status == CopyStatus.HELD:
                reservation = self.reservations_queries.held_for_customer(copy.id, customer_id, datetime.now(timezone.utc), lock=True)
                if reservation:
                    held_reservations[copy.id] = reservation
                    continue
            if copy.status != CopyStatus.AVAILABLE:
                raise BusinessError("Tồn kho đã thay đổi, hãy lập lại phiếu.")
        quote = self.quote(customer_id, lines, voucher_code, combo_ids)
        if expected_quote is not None and quote != expected_quote:
            raise BusinessError("Giá hoặc ưu đãi đã thay đổi. Hãy kiểm tra báo giá mới trước khi thanh toán.")
        code = order_code or f"PX{datetime.now():%y%m%d%H%M%S}{token_hex(4).upper()}"
        if self.orders_queries.fetch_checkout_check(code):
            raise BusinessError("Mã phiếu đã tồn tại.")
        order = Order(code=code, customer_id=customer_id, employee_id=employee_id,
                      gross_total=quote.gross, discount_total=quote.discount, deposit_total=quote.deposit)
        self.orders_queries.add_order(order)
        self.orders_queries.flush()
        for source, amount in quote.discount_sources.items():
            self.orders_queries.add_order_discount(OrderDiscount(order_id=order.id, source=source, amount=amount, source_code=quote.discount_source_codes.get(source)))
        customer = self.orders_queries.get_customer(customer_id)
        assert customer is not None
        for request in lines:
            copy = by_id[request.copy_id]
            if copy.id in held_reservations:
                held_reservations[copy.id].state = ReservationState.FULFILLED
            price = quote.line_prices[copy.id]
            deposit = Decimal("0")
            if request.action == LineAction.RENT:
                deposit = quote.line_deposits[copy.id]
            line = OrderLine(order_id=order.id, copy_id=copy.id, action=request.action, title_snapshot=copy.item.title, barcode_snapshot=copy.barcode,
                             unit_price=price, discount_amount=quote.line_discounts[copy.id], deposit_amount=deposit,
                             note="Đặt trước" if copy.id in held_reservations else None)
            self.orders_queries.add_order_line(line)
            self.orders_queries.flush()
            if copy.id in held_reservations:
                held_reservations[copy.id].fulfilled_line_id = line.id
            before = copy.status
            if request.action == LineAction.RENT:
                copy.status = CopyStatus.RENTED
                term = RentalTerm(line_id=line.id, due_date=request.due_date, issued_condition=copy.condition)
                self.orders_queries.add_rental_term(term)
                self.orders_queries.flush()
                for event, scheduled_for in scheduled_reminders(request.due_date):
                    for channel in ("EMAIL", "SMS"):
                        self.orders_queries.add_notification_outbox(NotificationOutbox(customer_id=customer_id, rental_term_id=term.id, channel=channel, event=event, scheduled_for=scheduled_for, dedupe_key=f'rental:{term.id}:{channel.lower()}:{event}'))
            else:
                copy.status = CopyStatus.SOLD
            self._status_history(copy, before, copy.status, f"Phiếu {code}", employee_id)
        paid = sum((Decimal(p.amount) for p in payments), Decimal("0"))
        for payment in payments:
            self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=order.id, customer_id=customer_id, employee_id=employee_id, method=payment.method, category='CHECKOUT', amount=Decimal(payment.amount)))
        if paid < quote.total_due:
            order.status = "PARTIALLY_PAID"
        self._audit(employee_id, "CHECKOUT", "Order", order.id, {
            "code": order.code, "customer_id": customer_id, "line_count": len(lines),
            "discount": str(quote.discount), "deposit": str(quote.deposit),
        })
        return order

    def query_active_rentals(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("due", False), customer_name: str = "") -> PagedResult[ActiveRental]:
        return self.orders_queries.query_active_rentals(page_request, sort, customer_name)

    def active_rentals(self) -> list[ActiveRental]:
        return list(self.query_active_rentals(PageRequest(1, 10_000)).items)

    def query_orders(self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created_at", True), start_on: date | None = None, end_on: date | None = None) -> PagedResult[OrderSummary]:
        return self.orders_queries.query_orders(text, page_request, sort, start_on, end_on)

    def list_orders(self, text: str = "", limit: int = 200) -> list[OrderSummary]:
        return list(self.query_orders(text, PageRequest(1, limit)).items)

    def order_detail(self, order_id: int) -> tuple[OrderSummary, list[OrderDetailLine]]:
        order, customer, employee = self.orders_queries.order_with_parties(order_id).one_or_none() or (None, None, None)
        if not order:
            raise BusinessError("Không tìm thấy phiếu.")
        lines = self.orders_queries.order_lines_with_copies(order_id).all()
        summary = OrderSummary(order.id, order.code, customer.full_name, employee.full_name, order.created_at, order.status, Decimal(order.gross_total) - Decimal(order.discount_total) + Decimal(order.deposit_total) - Decimal(order.deposit_applied or 0))
        return summary, [
            OrderDetailLine(
                title=line.title_snapshot,
                barcode=line.barcode_snapshot or (copy.barcode if copy else None),
                action=line.action,
                unit_price=Decimal(line.unit_price),
                deposit=Decimal(line.deposit_amount),
                due_date=term.due_date if term else None,
                rental_state=term.state if term else None,
                note=line.note,
            )
            for line, copy, term in lines
        ]

    def order_receipt(self, order_id: int) -> OrderReceipt:
        row = self.orders_queries.order_with_parties(order_id).one_or_none()
        if not row:
            raise BusinessError("Không tìm thấy phiếu.")
        order, customer, employee = row
        line_rows = self.orders_queries.order_lines_with_copies(order_id).all()
        discounts = tuple(
            ReceiptDiscount(discount.source, Decimal(discount.amount), discount.source_code)
            for discount in self.orders_queries.fetch_order_receipt_discounts(order_id)
        )
        payments = tuple(
            ReceiptPayment(payment.method, payment.category, Decimal(payment.amount), payment.created_at)
            for payment in self.orders_queries.fetch_order_receipt_payments(order_id)
        )
        checkout_paid = sum(
            (payment.amount for payment in payments if payment.category in ("CHECKOUT", "RENTAL_TO_SALE")), Decimal("0")
        )
        legacy_applied = sum((Decimal(line.discount_amount) for line, _copy, _term in line_rows
                              if line.source_rental_line_id and order.deposit_applied is None), Decimal("0"))
        applied_deposit = Decimal(order.deposit_applied or 0) + legacy_applied
        total_due = Decimal(order.gross_total) - Decimal(order.discount_total) + Decimal(order.deposit_total) - Decimal(order.deposit_applied or 0)
        return OrderReceipt(
            order_id=order.id,
            code=order.code,
            created_at=order.created_at,
            status=order.status,
            customer_name=customer.full_name,
            customer_phone=customer.phone,
            customer_email=customer.email,
            customer_address=customer.address,
            employee_name=employee.full_name,
            gross_total=Decimal(order.gross_total),
            discount_total=Decimal(order.discount_total) - legacy_applied,
            deposit_total=Decimal(order.deposit_total),
            total_due=total_due,
            checkout_paid=checkout_paid,
            balance_due=max(Decimal("0"), total_due - checkout_paid),
            lines=tuple(
                OrderReceiptLine(
                    title=line.title_snapshot,
                    barcode=line.barcode_snapshot or (copy.barcode if copy else None),
                    action=line.action,
                    unit_price=Decimal(line.unit_price),
                    discount_amount=Decimal(line.discount_amount) - (Decimal(line.discount_amount) if line.source_rental_line_id and order.deposit_applied is None else Decimal("0")),
                    net_amount=Decimal(line.unit_price) - (Decimal(line.discount_amount) if not line.source_rental_line_id or order.deposit_applied is not None else Decimal("0")),
                    deposit=Decimal(line.deposit_amount),
                    due_date=term.due_date if term else None,
                    rental_state=term.state.value if term else None,
                    note=line.note,
                )
                for line, copy, term in line_rows
            ),
            discounts=discounts,
            payments=payments,
            applied_deposit=applied_deposit,
        )

    def record_order_pdf_export(self, order_id: int, actor_id: int, layout: str, filename: str) -> None:
        if layout not in {"A4", "80mm"}:
            raise BusinessError("Mẫu PDF không hợp lệ.")
        if not self.orders_queries.get_order(order_id):
            raise BusinessError("Không tìm thấy phiếu.")
        self._audit(actor_id, "EXPORT_ORDER_PDF", "Order", order_id, {
            "layout": layout,
            "filename": filename,
        })

    def return_rentals(self, employee_id: int, customer_id: int, returns: list[RentalReturnInput | tuple[int, ReturnOutcome, str]], payment: PaymentInput | None = None, today: date | None = None) -> Decimal:
        today = today or date.today()
        receipt = ReturnReceipt(customer_id=customer_id, employee_id=employee_id, returned_on=today)
        self.orders_queries.add_return_receipt(receipt)
        self.orders_queries.flush()
        balance = Decimal("0")
        returned_item_ids: set[int] = set()
        order_deposits: dict[int, dict[int, Decimal]] = {}
        audit_lines = []
        for entry in returns:
            if isinstance(entry, tuple):
                term_id, outcome, note = entry
                condition = percent = status = damage_charge = None
            else:
                term_id, outcome, note = entry.term_id, entry.outcome, entry.note
                condition, percent, status = entry.condition, entry.condition_percent, entry.status
                damage_charge = entry.damage_charge
            if not isinstance(outcome, ReturnOutcome):
                raise BusinessError("Kết quả trả đĩa không hợp lệ.")
            if condition is not None and not isinstance(condition, CopyCondition):
                raise BusinessError("Tình trạng đĩa không hợp lệ.")
            if percent is not None and (not Decimal(percent).is_finite() or not 0 <= Decimal(percent) <= 100):
                raise BusinessError("Tình trạng phải từ 0 đến 100%.")
            allowed = {CopyStatus.AVAILABLE, CopyStatus.INSPECTION, CopyStatus.REPAIR, CopyStatus.RETIRED}
            if status is not None and (status != CopyStatus.LOST if outcome == ReturnOutcome.LOST else status not in allowed):
                raise BusinessError("Trạng thái sau trả không hợp lệ.")
            term = self.orders_queries.fetch_return_rentals_term(term_id)
            if not term or term.state != RentalState.ACTIVE:
                raise BusinessError("Dòng thuê không còn hoạt động.")
            if term.line.order.customer_id != customer_id:
                raise BusinessError("Dòng thuê không thuộc khách hàng đang trả.")
            copy = term.line.copy
            assert copy is not None
            late = late_fee(term.due_date, today, Decimal(term.late_daily_rate))
            try:
                damage = damage_fee(copy.item.replacement_value, outcome, damage_charge)
            except ValueError as exc:
                raise BusinessError(str(exc)) from exc
            charges = late + damage
            if late:
                self.orders_queries.add_penalty_charge(PenaltyCharge(rental_term_id=term.id, kind='LATE', amount=late, reason='Trả quá hạn'))
            if damage:
                self.orders_queries.add_penalty_charge(PenaltyCharge(rental_term_id=term.id, kind=outcome.value, amount=damage, reason=note or outcome.value))
            order = term.line.order
            if order.id not in order_deposits:
                _, order_deposits[order.id] = self.orders_queries.rental_order_amounts([order])
            deposit = order_deposits[order.id][term.line_id]
            balance += charges - deposit
            before = copy.status
            before_condition, before_percent = copy.condition, copy.condition_percent
            if outcome == ReturnOutcome.NORMAL:
                copy.status = CopyStatus.AVAILABLE
            elif outcome in (ReturnOutcome.LIGHT_DAMAGE, ReturnOutcome.HEAVY_DAMAGE):
                copy.status = CopyStatus.REPAIR
                copy.condition = CopyCondition.DAMAGED
                copy.condition_percent = Decimal("0")
            else:
                copy.status = CopyStatus.LOST
                term.state = RentalState.LOST
            if condition is not None:
                copy.condition = condition
            if percent is not None:
                copy.condition_percent = Decimal(percent)
            if status is not None:
                copy.status = status
            if copy.status == CopyStatus.AVAILABLE:
                returned_item_ids.add(copy.item_id)
            if term.state != RentalState.LOST:
                term.state = RentalState.RETURNED
            term.returned_on = today
            self.orders_queries.add_return_line(ReturnLine(receipt_id=receipt.id, rental_term_id=term.id, outcome=outcome.value, note=note or None))
            self._status_history(copy, before, copy.status, f"Trả đĩa: {outcome.value}", employee_id)
            audit_lines.append({"term_id": term.id, "before_condition": before_condition.value,
                                "before_percent": str(before_percent), "condition": copy.condition.value,
                                "percent": str(copy.condition_percent), "status": copy.status.value})
        for item_id in returned_item_ids:
            self.allocate_waiting_reservations(item_id)
        amount = Decimal(payment.amount) if payment else Decimal("0")
        if not amount.is_finite() or not 0 <= amount <= max(Decimal("0"), balance):
            raise BusinessError("Khoản thu thêm không hợp lệ.")
        if balance < 0:
            self.orders_queries.add_payment_transaction(PaymentTransaction(customer_id=customer_id, employee_id=employee_id, method=PaymentMethod.CASH, category='DEPOSIT_REFUND', amount=balance))
        elif payment and amount:
            self.orders_queries.add_payment_transaction(PaymentTransaction(customer_id=customer_id, employee_id=employee_id, method=payment.method, category='RETURN_SETTLEMENT', amount=amount))
        self._audit(employee_id, "RETURN_RENTAL", "ReturnReceipt", receipt.id, {
            "customer_id": customer_id, "lines": audit_lines, "balance": str(balance),
        })
        return balance

    def extend_rental(self, rental_term_id: int, employee_id: int, new_due_date: date | None = None,
                      fee: Decimal | None = None, method: PaymentMethod = PaymentMethod.CASH,
                      today: date | None = None) -> RentalTerm:
        today = today or date.today()
        term = self.orders_queries.fetch_extend_rental_term(rental_term_id)
        if not term or term.state != RentalState.ACTIVE:
            raise BusinessError("Chỉ có thể gia hạn dòng thuê đang hoạt động.")
        has_waiting_reservation = self.orders_queries.fetch_extend_rental_has_waiting_reservation(term) is not None
        if term.due_date < today or has_waiting_reservation:
            self._require_manager(employee_id)
        old_due_date = term.due_date
        copy = term.line.copy
        assert copy is not None
        new_due_date = new_due_date or old_due_date + timedelta(days=3)
        if new_due_date <= max(old_due_date, today):
            raise BusinessError("Ngày trả mới phải sau hạn hiện tại và hôm nay.")
        price = Decimal(fee) if fee is not None else self._copy_price(copy, LineAction.RENT)
        if not price.is_finite() or price < 0:
            raise BusinessError("Phí gia hạn phải là số không âm.")
        if not isinstance(method, PaymentMethod):
            raise BusinessError("Phương thức thanh toán không hợp lệ.")
        late = late_fee(old_due_date, today, Decimal(term.late_daily_rate))
        customer_id = self.orders_queries.get_order(term.line.order_id).customer_id
        if late:
            self.orders_queries.add_penalty_charge(PenaltyCharge(rental_term_id=term.id, kind="LATE", amount=late, reason="Gia hạn quá hạn"))
            self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=term.line.order_id, customer_id=customer_id, employee_id=employee_id, method=method, category="EXTENSION_LATE", amount=late))
        if price:
            self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=term.line.order_id, customer_id=customer_id, employee_id=employee_id, method=method, category="RENTAL_EXTENSION", amount=price))
        term.due_date = new_due_date
        self.orders_queries.add_rental_extension(RentalExtension(rental_term_id=term.id, old_due_date=old_due_date, new_due_date=new_due_date, fee=price, employee_id=employee_id))
        self._audit(employee_id, "EXTEND_RENTAL", "RentalTerm", term.id, {"old_due_date": str(old_due_date), "due_date": str(new_due_date), "fee": str(price), "late": str(late)})
        return term

    def rental_to_sale(self, rental_term_id: int, employee_id: int, payment: PaymentInput) -> Order:
        if Decimal(payment.amount) < 0:
            raise BusinessError("Khoản thanh toán không được âm.")
        term = self.orders_queries.fetch_rental_to_sale_term(rental_term_id)
        if not term or term.state != RentalState.ACTIVE:
            raise BusinessError("Dòng thuê không thể chuyển thành mua.")
        source = term.line
        copy = source.copy
        assert copy is not None
        if not copy.can_sell or not copy.item.can_sell:
            raise BusinessError("Bản đĩa đang thuê không cho phép bán.")
        order = self.orders_queries.get_order(source.order_id)
        if order.status == "PARTIALLY_PAID":
            raise BusinessError("Phiếu thuê chưa thanh toán đủ; không thể cấn tiền cọc chưa xác nhận đã thu.")
        sale_price = self._copy_price(copy, LineAction.BUY)
        applied_deposit = min(Decimal(source.deposit_amount), sale_price)
        sale = Order(
            code=f"PB{datetime.now():%y%m%d%H%M%S}{token_hex(2).upper()}",
            customer_id=order.customer_id,
            employee_id=employee_id,
            gross_total=sale_price,
            discount_total=Decimal("0"),
            deposit_total=Decimal("0"),
            deposit_applied=applied_deposit,
            status="PARTIALLY_PAID" if Decimal(payment.amount) < sale_price - applied_deposit else "CONFIRMED",
        )
        self.orders_queries.add_order(sale)
        self.orders_queries.flush()
        self.orders_queries.add_order_line(OrderLine(order_id=sale.id, copy_id=copy.id, action=LineAction.BUY, title_snapshot=copy.item.title, barcode_snapshot=copy.barcode, unit_price=sale_price, discount_amount=Decimal("0"), source_rental_line_id=source.id))
        term.state = RentalState.PURCHASED
        before = copy.status
        copy.status = CopyStatus.SOLD
        self._status_history(copy, before, copy.status, f"Chuyển thuê thành mua: {sale.code}", employee_id)
        self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=sale.id, customer_id=order.customer_id, employee_id=employee_id, method=payment.method, category='RENTAL_TO_SALE', amount=payment.amount))
        excess_deposit = Decimal(source.deposit_amount) - applied_deposit
        if excess_deposit:
            self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=sale.id, customer_id=order.customer_id, employee_id=employee_id, method=payment.method, category='DEPOSIT_REFUND', amount=-excess_deposit, note='Hoàn phần cọc vượt giá bán'))
        self._audit(employee_id, "RENTAL_TO_SALE", "Order", sale.id, {"source_line_id": source.id, "deposit_applied": str(applied_deposit)})
        return sale

    def returnable_sales(self, today: date | None = None) -> list[ReturnableSale]:
        today = today or date.today()
        rows = self.orders_queries.fetch_returnable_sales_rows(today).all()
        return [
            ReturnableSale(
                line_id=line.id,
                customer_name=customer.full_name,
                title=line.title_snapshot,
                barcode=copy.barcode,
                sold_on=local_datetime(order.created_at).date(),
                expires_on=local_datetime(order.created_at).date() + timedelta(days=7),
            )
            for line, order, customer, copy in rows
            if sale_return_allowed(local_datetime(order.created_at).date(), today)
        ]

    def return_sale(
        self,
        sale_line_id: int,
        employee_id: int,
        today: date | None = None,
        condition: CopyCondition = CopyCondition.GOOD,
        deduction: Decimal = Decimal("0"),
        note: str = "",
    ) -> Decimal:
        today = today or date.today()
        line = self.orders_queries.fetch_return_sale_line(sale_line_id)
        if not line or not sale_return_allowed(local_datetime(line.order.created_at).date(), today):
            raise BusinessError("Dòng bán không còn trong thời hạn hoàn trả 7 ngày.")
        copy = line.copy
        if not copy or copy.status != CopyStatus.SOLD:
            raise BusinessError("Bản đĩa này không ở trạng thái đã bán.")
        if condition not in (CopyCondition.GOOD, CopyCondition.WORN, CopyCondition.DAMAGED):
            raise BusinessError("Tình trạng đĩa hoàn không hợp lệ.")
        if condition != CopyCondition.GOOD:
            self._require_manager(employee_id)
        gross_refund = Decimal(line.unit_price) - Decimal(line.discount_amount)
        if line.source_rental_line_id:
            source = self.orders_queries.get_order_line(line.source_rental_line_id)
            if not source or source.order.status == "PARTIALLY_PAID":
                raise BusinessError("Không xác định được số tiền cọc đã thu của phiếu thuê; cần đối soát trước khi hoàn.")
            applied = Decimal(line.order.deposit_applied) if line.order.deposit_applied is not None else Decimal(line.discount_amount)
            paid = sum((Decimal(row.amount) for row in self.orders_queries.fetch_order_receipt_payments(line.order_id)
                        if row.category == "RENTAL_TO_SALE" and row.amount > 0), Decimal("0"))
            gross_refund = min(Decimal(line.unit_price), applied + paid)
        elif line.order.status == "PARTIALLY_PAID":
            raise BusinessError("Phiếu chưa thanh toán đủ; cần đối soát trước khi hoàn hàng.")
        deduction = Decimal(deduction)
        if deduction < 0 or deduction > gross_refund:
            raise BusinessError("Mức khấu trừ hoàn hàng không hợp lệ.")
        refund = gross_refund - deduction
        if condition != copy.condition:
            maximum = {CopyCondition.GOOD: Decimal("90"), CopyCondition.WORN: Decimal("70"), CopyCondition.DAMAGED: Decimal("0")}[condition]
            copy.condition_percent = min(Decimal(copy.condition_percent), maximum)
        copy.condition = condition
        copy.status = CopyStatus.INSPECTION
        status_note = note.strip() or "Khách trả hàng bán"
        if deduction:
            status_note = f"{status_note}; khấu trừ {deduction:,.0f}"
        self._status_history(copy, CopyStatus.SOLD, CopyStatus.INSPECTION, status_note, employee_id)
        self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=line.order_id, customer_id=line.order.customer_id, employee_id=employee_id, method=PaymentMethod.CASH, category='SALE_REFUND', amount=-refund))
        self.orders_queries.add_sale_return(SaleReturn(sale_line_id=line.id, employee_id=employee_id, returned_on=today, refund_amount=refund, condition_at_return=condition.value, note=status_note))
        self._audit(employee_id, "RETURN_SALE", "SaleReturn", line.id, {"refund": str(refund), "condition": condition.value})
        return refund

    def query_inventory(self, status: CopyStatus | None = None, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("title"), text: str = "", item_id: int | None = None, condition: CopyCondition | None = None, media: str = "", rentable: bool = False, sellable: bool = False, location=("", "", "")) -> PagedResult[InventoryCopy]:
        return self.inventory_queries.query_inventory(status, page_request, sort, text, item_id, condition, media, rentable, sellable, location)

    def inventory_groups(self, status, text, condition, media, rentable, sellable, page_request, descending=False, item_id=None, location=("", "", "")):
        return self.inventory_queries.query_groups(status, text, condition, media, rentable, sellable, page_request, descending, item_id, location)

    def inventory_group_episodes(self, show_id, status, text, condition, media, rentable, sellable, item_id=None, location=("", "", "")):
        return self.inventory_queries.group_episodes(show_id, status, text, condition, media, rentable, sellable, item_id, location)

    def list_inventory(self, status: CopyStatus | None = None, limit: int = 500) -> list[InventoryCopy]:
        return list(self.query_inventory(status, PageRequest(1, limit), SortSpec("barcode")).items)

    def inspect_copy(
        self,
        copy_id: int,
        employee_id: int,
        target_status: CopyStatus,
        note: str = "",
    ) -> PhysicalCopy:
        if target_status not in (CopyStatus.AVAILABLE, CopyStatus.REPAIR, CopyStatus.RETIRED):
            raise BusinessError("Kết quả kiểm tra đĩa không hợp lệ.")
        copy = self.inventory_queries.lock_copy(copy_id)
        if not copy or copy.status != CopyStatus.INSPECTION:
            raise BusinessError("Chỉ có thể duyệt đĩa đang chờ kiểm tra.")
        before = copy.status
        copy.status = target_status
        if target_status == CopyStatus.REPAIR:
            copy.condition = CopyCondition.DAMAGED
            copy.condition_percent = Decimal("0")
        self._status_history(copy, before, target_status, note or "Duyệt sau kiểm tra", employee_id)
        if target_status == CopyStatus.AVAILABLE:
            self.allocate_waiting_reservations(copy.item_id)
        return copy

    def reserve(self, customer_id: int, item_ids: list[int], actor_id: int | None = None) -> list[Reservation]:
        if not item_ids:
            raise BusinessError("Cần chọn ít nhất một phim hoặc tập phim để đặt trước.")
        if not self.reservations_queries.get_customer(customer_id):
            raise BusinessError("Không tìm thấy khách hàng.")
        items = list(self.reservations_queries.fetch_reserve_items(item_ids))
        if len(items) != len(set(item_ids)):
            raise BusinessError("Có phim hoặc tập phim không tồn tại.")
        if any(not item.can_rent and not item.can_sell for item in items):
            raise BusinessError("Phim đặt trước phải cho phép thuê hoặc bán.")
        reservations = []
        for item_id in set(item_ids):
            duplicate = self.reservations_queries.fetch_reserve_duplicate(customer_id, item_id)
            if duplicate:
                raise BusinessError("Khách hàng đã có đặt trước đang hiệu lực cho item này.")
            reservation = Reservation(customer_id=customer_id, item_id=item_id)
            self.reservations_queries.add_reservation(reservation)
            reservations.append(reservation)
        self.reservations_queries.flush()
        for item_id in {reservation.item_id for reservation in reservations}:
            self.allocate_waiting_reservations(item_id)
        self._audit(actor_id, "CREATE_RESERVATION", "Reservation", ",".join(str(row.id) for row in reservations), {
            "customer_id": customer_id, "item_ids": sorted({row.item_id for row in reservations}),
        })
        return reservations

    def cancel_reservation(self, reservation_id: int, actor_id: int) -> None:
        self.cancel_reservations([reservation_id], actor_id)

    def cancel_reservations(self, reservation_ids: list[int], actor_id: int) -> None:
        ids = sorted(set(reservation_ids))
        if not ids:
            raise BusinessError("Hãy chọn ít nhất một lượt đặt trước.")
        # Lock the copies first, as checkout and hold expiry do.
        allocated = self.reservations_queries.allocated_copy_ids(ids)
        copy_ids = sorted({copy_id for copy_id in allocated.values() if copy_id is not None})
        copies = {copy_id: self.reservations_queries.lock_copy(copy_id) for copy_id in copy_ids}
        reservations = self.reservations_queries.lock_reservations(ids)
        if len(reservations) != len(ids):
            raise BusinessError("Không tìm thấy lượt đặt trước.")
        for reservation in reservations:
            if reservation.state not in (ReservationState.WAITING, ReservationState.HELD):
                raise BusinessError("Chỉ có thể hủy lượt đang chờ hoặc đang giữ đĩa.")
            if reservation.allocated_copy_id != allocated.get(reservation.id):
                raise BusinessError("Lượt đặt trước vừa thay đổi. Hãy chọn lại để hủy.")

        released_items = set()
        for reservation in reservations:
            previous_state = reservation.state
            copy_id = reservation.allocated_copy_id
            reservation.state = ReservationState.CANCELLED
            reservation.allocated_copy_id = None
            reservation.hold_until = None
            copy = copies.get(copy_id) if copy_id is not None else None
            if previous_state == ReservationState.HELD and copy is not None and copy.status == CopyStatus.HELD:
                copy.status = CopyStatus.AVAILABLE
                self._status_history(copy, CopyStatus.HELD, CopyStatus.AVAILABLE, "Hủy đặt trước", actor_id)
                released_items.add(reservation.item_id)
            self._audit(actor_id, "CANCEL_RESERVATION", "Reservation", reservation.id, {
                "previous_state": previous_state.value, "copy_id": copy_id,
            })
        # Reallocate only after all selected rows have left the queue.
        for item_id in sorted(released_items):
            self.allocate_waiting_reservations(item_id)

    def query_reservations(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created", True), *, text: str = "") -> PagedResult[ReservationView]:
        return self.reservations_queries.query_reservations(page_request, sort, text=text)

    def customer_preorder_copies(self, customer_id: int) -> list[CopyChoice]:
        self.expire_reservation_holds()
        self.allocate_released_reservations()
        choices = []
        for copy in self.reservations_queries.held_copies_for_customer(customer_id, datetime.now(timezone.utc)):
            item = copy.item
            action = (LineAction.RENT if item.can_rent and copy.can_rent else
                      LineAction.BUY if item.can_sell and copy.can_sell else None)
            if action is None:
                continue
            # Use the same pricing and availability rules as manual selection.
            choices.extend(choice for choice in self.checkout_copies(item.id, action, customer_id=customer_id)
                           if choice.copy_id == copy.id)
        return choices

    def list_reservations(self) -> list[ReservationView]:
        return list(self.query_reservations(PageRequest(1, 10_000)).items)

    def expire_reservation_holds(self, now: datetime | None = None, item_id: int | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        copy_ids = self.reservations_queries.expired_hold_copy_ids(now, item_id)
        self.reservations_queries.lock_copies(copy_ids)
        reservations = list(
            self.reservations_queries.fetch_expire_reservation_holds_reservations(now, item_id)
        )
        item_ids: set[int] = set()
        for reservation in reservations:
            copy_id = reservation.allocated_copy_id
            copy = self.reservations_queries.lock_copy(copy_id) if copy_id is not None else None
            if copy and copy.status == CopyStatus.HELD:
                copy.status = CopyStatus.AVAILABLE
                self._status_history(copy, CopyStatus.HELD, CopyStatus.AVAILABLE, "Hết hạn giữ chỗ")
            reservation.state = ReservationState.EXPIRED
            item_ids.add(reservation.item_id)
        for item_id in item_ids:
            self.allocate_waiting_reservations(item_id)
        self.reservation_state_changed |= bool(reservations)
        return len(reservations)

    def allocate_waiting_reservations(self, item_id: int) -> int:
        if not self.reservations_queries.has_waiting(item_id):
            return 0
        items = list(self.reservations_queries.fetch_reserve_items([item_id]))
        if not items or (items[0].release_date and items[0].release_date > date.today()):
            return 0
        copies = list(self.reservations_queries.fetch_allocate_waiting_reservations_copies(item_id))
        reservations = list(self.reservations_queries.fetch_allocate_waiting_reservations_reservations(item_id))
        count = 0
        for copy, reservation in zip(copies, reservations):
            copy.status = CopyStatus.HELD
            reservation.state = ReservationState.HELD
            reservation.allocated_copy_id = copy.id
            reservation.hold_until = datetime.now(timezone.utc) + timedelta(hours=24)
            self._status_history(copy, CopyStatus.AVAILABLE, CopyStatus.HELD, "Giữ cho đặt trước")
            count += 1
        self.reservation_state_changed |= count > 0
        return count

    def allocate_for_checkout(self, copy_ids: list[int]) -> int:
        if not copy_ids:
            return 0
        now = datetime.now(timezone.utc)
        expired_items = self.reservations_queries.expired_items_for_copies(copy_ids, now)
        expired = sum(self.expire_reservation_holds(now, item_id) for item_id in expired_items)
        item_ids = self.reservations_queries.released_waiting_for_copies(copy_ids, date.today())
        return expired + sum(self.allocate_waiting_reservations(item_id) for item_id in item_ids)

    def allocate_released_reservations(self) -> int:
        return sum(self.allocate_waiting_reservations(item_id) for item_id in self.reservations_queries.released_waiting_item_ids(date.today()))

    def dashboard(self) -> dict[str, Decimal | int]:
        today = datetime.now(ZoneInfo("Asia/Ho_Chi_Minh")).date()
        rented = self.dashboard_queries.fetch_dashboard_rented() or 0
        available = self.dashboard_queries.fetch_dashboard_available() or 0
        overdue = self.dashboard_queries.fetch_dashboard_overdue(today) or 0
        held = self.dashboard_queries.fetch_dashboard_held() or 0
        cash_flow = self.dashboard_queries.fetch_dashboard_cash_flow(today) or Decimal("0")
        return {"available": available, "rented": rented, "overdue": overdue, "reservations": held, "cash_flow": Decimal(cash_flow)}

    def dashboard_low_stock(self):
        return [(int(item_id), title, int(rentable), int(sellable)) for item_id, title, rentable, sellable in self.dashboard_queries.low_stock()]

    def query_dashboard_low_stock(self, page_request: PageRequest = PageRequest()):
        page = self.dashboard_queries.low_stock_page(page_request)
        return PagedResult(tuple((int(item_id), title, int(rentable), int(sellable))
                                 for item_id, title, rentable, sellable in page.items),
                           page.page, page.page_size, page.total_items, page.total_pages)

    def dashboard_popular(self, action: LineAction):
        if action not in (LineAction.RENT, LineAction.BUY):
            raise BusinessError("Loại giao dịch không hợp lệ.")
        since = datetime.now(timezone.utc) - timedelta(days=30)
        return [(title, int(count)) for title, count in self.dashboard_queries.popular(action, since)]

    def dashboard_upcoming(self):
        return [(int(item_id), title, release_date) for item_id, title, release_date in self.dashboard_queries.upcoming(date.today())]

    def query_dashboard_upcoming(self, page_request: PageRequest = PageRequest()):
        page = self.dashboard_queries.upcoming_page(date.today(), page_request)
        return PagedResult(tuple((int(item_id), title, release_date) for item_id, title, release_date in page.items),
                           page.page, page.page_size, page.total_items, page.total_pages)

    def dashboard_discovery(self):
        rows = self.dashboard_queries.discovery(date.today(), datetime.now(timezone.utc) - timedelta(days=30))
        return [(int(item_id), title, int(count), bool(active), Decimal(percent), starts, ends)
                for item_id, title, count, active, percent, starts, ends in rows]

    def dashboard_random(self):
        return [(int(item_id), title) for item_id, title in self.dashboard_queries.random_items(date.today())]

    def set_discovery_discount(self, item_id: int, percent: Decimal, active: bool,
                               starts: date | None, ends: date | None, actor_id: int):
        self._require_manager(actor_id)
        percent = Decimal(percent)
        if not percent.is_finite() or not 0 <= percent <= 100:
            raise BusinessError("Tỷ lệ giảm phải từ 0 đến 100%.")
        if starts and ends and starts > ends:
            raise BusinessError("Ngày kết thúc không được trước ngày bắt đầu.")
        item = self.catalog_item(item_id)
        item.discovery_discount_percent = percent
        item.discovery_discount_active = active
        item.discovery_discount_starts = starts
        item.discovery_discount_ends = ends
        self._audit(actor_id, "UPDATE_DISCOVERY_DISCOUNT", "CatalogItem", item.id,
                    {"percent": str(percent), "active": active, "starts": str(starts) if starts else None, "ends": str(ends) if ends else None})

    def today_recommendations(self, limit: int = 8) -> list[Recommendation]:
        return today_recommendations(
            self.recommendation_repository, limit, self.gemini_api_key, self.gemini_generation_model,
            self.gemini_factory,
        )

    def customer_recommendations(self, customer_id: int, limit: int = 8) -> list[Recommendation]:
        if not self.customers_queries.customer(customer_id):
            raise BusinessError("Không tìm thấy khách hàng.")
        return for_customer(
            self.recommendation_repository, customer_id, limit, self.gemini_api_key, self.gemini_generation_model,
            self.gemini_factory,
        )

    def query_notifications(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("scheduled", True)) -> PagedResult[NotificationSummary]:
        return self.notifications_queries.query_notifications(page_request, sort)

    def list_notifications(self, limit: int = 300) -> list[NotificationSummary]:
        return list(self.query_notifications(PageRequest(1, limit)).items)

    def query_audit_logs(
        self,
        filters: AuditQuery = AuditQuery(),
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("created", True),
    ) -> PagedResult[AuditView]:
        return self.audit_queries.query_audit_logs(filters, page_request, sort)

    def ensure_mock_fixtures(self, actor_id: int) -> MockFixtureResult:
        """Create stable fixtures in a transaction separate from daily mock orders."""
        self._require_manager(actor_id)
        today = date.today()
        combo_count = voucher_count = membership_count = 0
        item_ids = list(self.mock_queries.fetch_ensure_mock_fixtures_item_ids())
        show_ids = list(self.mock_queries.fetch_ensure_mock_fixtures_show_ids())
        if len(item_ids) < 20 or len(show_ids) < 10:
            raise BusinessError("Kho chưa đủ phim/tập còn thuê để tạo 20 combo mock.")
        for index in range(10):
            name = f"MOCK-COMBO-FIXED-{index + 1:02d}"
            if self.mock_queries.combo_by_name(name):
                continue
            combo = Combo(name=name, rule_type="FIXED", discount_amount=Decimal("10000"), active=True)
            self.mock_queries.add_combo(combo)
            self.mock_queries.flush()
            self.mock_queries.add_combo_item_batch([ComboItem(combo_id=combo.id, item_id=item_ids[index * 2]), ComboItem(combo_id=combo.id, item_id=item_ids[index * 2 + 1])])
            combo_count += 1
        for index, show_id in enumerate(show_ids, start=1):
            name = f"MOCK-COMBO-SHOW-{index:02d}"
            if self.mock_queries.combo_by_name(name):
                continue
            self.mock_queries.add_combo(Combo(name=name, rule_type='EPISODE_SHOW', show_id=show_id, required_count=2, discount_amount=Decimal('12000'), active=True))
            combo_count += 1
        for index in range(1, 51):
            code = f"MOCKV{index:02d}"
            if self.mock_queries.voucher_by_code(code):
                continue
            starts, ends = ((today - timedelta(days=60), None) if index <= 20 else
                            ((today - timedelta(days=180), today - timedelta(days=1)) if index <= 35 else
                             (today + timedelta(days=30), today + timedelta(days=90))))
            self.mock_queries.add_voucher(Voucher(code=code, percent_off=Decimal('10') if index % 2 else None, amount_off=Decimal('15000') if index % 2 == 0 else None, starts_on=starts, ends_on=ends))
            voucher_count += 1
        customers = list(self.mock_queries.customers())
        occupied = set(self.mock_queries.premium_member_ids())
        active = set(self.mock_queries.fetch_ensure_mock_fixtures_active(today))
        expired = set(self.mock_queries.fetch_ensure_mock_fixtures_expired(today))
        for customer in customers:
            if len(active) >= 300:
                break
            if customer.id in occupied:
                continue
            starts = today - timedelta(days=30 + customer.id % 20)
            self.mock_queries.add_premium_membership(PremiumMembership(customer_id=customer.id, starts_on=starts, ends_on=starts + timedelta(days=364), price_paid=Decimal('499000')))
            occupied.add(customer.id); active.add(customer.id); membership_count += 1
        for customer in customers:
            if len(expired) >= 150:
                break
            if customer.id in occupied:
                continue
            starts = today - timedelta(days=500 + customer.id % 40)
            self.mock_queries.add_premium_membership(PremiumMembership(customer_id=customer.id, starts_on=starts, ends_on=starts + timedelta(days=89), price_paid=Decimal('159000')))
            occupied.add(customer.id); expired.add(customer.id); membership_count += 1
        self._audit(actor_id, "CREATE_MOCK_FIXTURES", "MockFixtures", "20260908", {"combos": combo_count, "vouchers": voucher_count, "memberships": membership_count})
        return MockFixtureResult(combo_count, voucher_count, membership_count)

    def seed_mock_day(self, business_date: date, actor_id: int, volume_per_day: int = 250) -> int:
        self._require_manager(actor_id)
        today = date.today()
        if business_date > today or not 1 <= volume_per_day <= 250:
            raise BusinessError("Mock chỉ hỗ trợ ngày đến hôm nay và tối đa 250 phiếu/ngày.")
        if self.mock_queries.fetch_seed_mock_day_check(business_date):
            return 0
        customers = list(self.mock_queries.customers())
        available = list(self.mock_queries.fetch_seed_mock_day_available(volume_per_day))
        if not customers or len(available) < volume_per_day * 2:
            raise BusinessError("Kho hoặc khách hàng không đủ để tạo dữ liệu mock.")
        combos = list(self.mock_queries.fetch_seed_mock_day_combos())
        active_vouchers = list(self.mock_queries.fetch_seed_mock_day_active_vouchers(today))
        rng = Random(business_date.toordinal())

        def action(copy: PhysicalCopy) -> LineAction:
            rentable = copy.can_rent and copy.item.can_rent
            sellable = copy.can_sell and copy.item.can_sell
            return LineAction.BUY if sellable and (not rentable or rng.random() < 0.20) else LineAction.RENT

        for number in range(1, volume_per_day + 1):
            selected: list[PhysicalCopy] = []
            combo_id: int | None = None
            if combos and rng.random() < 0.20:
                combo = combos[rng.randrange(len(combos))]
                if combo.rule_type == "FIXED":
                    for item_id in self.mock_queries.fetch_seed_mock_day_rows_2(combo):
                        copy = next((copy for copy in available if copy.item_id == item_id), None)
                        if not copy:
                            selected.clear(); break
                        selected.append(copy)
                else:
                    seen_items: set[int] = set()
                    for copy in available:
                        if copy.item.show_id == combo.show_id and copy.item.item_type == ItemType.EPISODE and copy.item_id not in seen_items:
                            selected.append(copy); seen_items.add(copy.item_id)
                        if len(selected) >= (combo.required_count or 2):
                            break
                if len(selected) >= 2:
                    combo_id = combo.id
                else:
                    selected.clear()
            # Small test/demo inventories can legitimately have only two or
            # three valid copies.  Never request more lines than the pool can
            # supply for this order.
            target = min(rng.randint(2, 4), len(available))
            while len(selected) < target:
                candidates = [copy for copy in available if copy not in selected]
                if not candidates:
                    raise BusinessError("Kho hết đĩa hợp lệ trong lúc tạo mock.")
                selected.append(candidates[rng.randrange(len(candidates))])
            for copy in selected:
                available.remove(copy)
            actions = [action(copy) for copy in selected]
            customer = customers[rng.randrange(len(customers))]
            lines = [CheckoutLine(copy.id, choice, business_date + timedelta(days=3) if choice == LineAction.RENT else None) for copy, choice in zip(selected, actions, strict=True)]
            voucher = active_vouchers[rng.randrange(len(active_vouchers))] if active_vouchers and rng.random() < 0.35 else None
            quote = self.quote(customer.id, lines, voucher, [combo_id] if combo_id else None)
            order = self.checkout(customer.id, actor_id,  lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)], voucher, [combo_id] if combo_id else None, order_code=f"MOCK-{business_date:%Y%m%d}-{number:03d}")
            timestamp = datetime.combine(business_date, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
            order.created_at = order.updated_at = timestamp
            for payment in self.mock_queries.payments_for_order(order):
                payment.created_at = payment.updated_at = timestamp
            if business_date < today:
                terms = list(self.mock_queries.rentals_for_order(order))
                if terms:
                    receipt = ReturnReceipt(customer_id=customer.id, employee_id=actor_id, returned_on=business_date + timedelta(days=3))
                    self.mock_queries.add_return_receipt(receipt)
                    self.mock_queries.flush()
                    refund = Decimal("0")
                    for term in terms:
                        term.state, term.returned_on = RentalState.RETURNED, term.due_date
                        copy = self.mock_queries.get_physical_copy(term.line.copy_id)
                        if copy:
                            copy.status = CopyStatus.AVAILABLE
                        self.mock_queries.add_return_line(ReturnLine(receipt_id=receipt.id, rental_term_id=term.id, outcome='NORMAL'))
                        refund += Decimal(term.line.deposit_amount)
                    if refund:
                        self.mock_queries.add_payment_transaction(PaymentTransaction(order_id=order.id, customer_id=customer.id, employee_id=actor_id, method=PaymentMethod.CASH, category='DEPOSIT_REFUND', amount=-refund, note='Mock historical return', created_at=timestamp, updated_at=timestamp))
        self.mock_queries.add_mock_daily_run(MockDailyRun(business_date=business_date, seed_version='20260908', actor_id=actor_id, stats={'orders': volume_per_day, 'volume': volume_per_day}))
        self._audit(actor_id, "GENERATE_MOCK_DAY", "MockDailyRun", business_date.isoformat(), {"orders": volume_per_day})
        return volume_per_day

    def _ensure_mock_fixtures(self, actor_id: int) -> None:
        """Create stable promotion/Premium fixtures once without duplicating rows."""
        customers = list(self.mock_queries.fetch_ensure_mock_fixtures_customers_2())
        existing_members = set(self.mock_queries.premium_member_ids())
        for index, customer in enumerate(customers):
            if customer.id in existing_members:
                continue
            active = index < 300
            starts = date.today() - timedelta(days=(index % 20) if active else 500 + index)
            days = 90 if index % 3 else 365
            ends = starts + timedelta(days=days - 1)
            membership = PremiumMembership(
                customer_id=customer.id, starts_on=starts, ends_on=ends,
                price_paid=Decimal("159000") if days == 90 else Decimal("499000"),
            )
            self.mock_queries.add_premium_membership(membership)
        for index in range(1, 51):
            code = f"MOCKV{index:02d}"
            if self.mock_queries.voucher_by_code(code):
                continue
            starts = date.today() - timedelta(days=60) if index <= 20 else (
                date.today() - timedelta(days=180) if index <= 35 else date.today() + timedelta(days=30)
            )
            ends = None if index <= 20 else (date.today() - timedelta(days=1) if index <= 35 else date.today() + timedelta(days=90))
            self.mock_queries.add_voucher(Voucher(code=code, percent_off=Decimal('10') if index % 2 else None, amount_off=Decimal('15000') if index % 2 == 0 else None, starts_on=starts, ends_on=ends))
        item_ids = list(self.mock_queries.fetch_ensure_mock_fixtures_item_ids_2())
        existing = int(self.mock_queries.fetch_ensure_mock_fixtures_existing() or 0)
        for index in range(existing, min(20, len(item_ids) // 2)):
            combo = Combo(name=f"Combo mock {index + 1:02d}", rule_type="FIXED", discount_amount=Decimal("10000"), active=True)
            self.mock_queries.add_combo(combo); self.mock_queries.flush()
            self.mock_queries.add_combo_item_batch([ComboItem(combo_id=combo.id, item_id=item_ids[index * 2]), ComboItem(combo_id=combo.id, item_id=item_ids[index * 2 + 1])])

    def _seed_mock_range_legacy(
        self,
        start_on: date,
        end_on: date,
        actor_id: int,
        volume_per_day: int = 250,
    ) -> MockSeedResult:
        self._require_manager(actor_id)
        if end_on < start_on or (end_on - start_on).days > 30 or not 1 <= volume_per_day <= 250:
            raise BusinessError("Khoảng mock tối đa 31 ngày và tối đa 250 phiếu mỗi ngày.")
        self._ensure_mock_fixtures(actor_id)
        customers = list(self.mock_queries.customers())
        if not customers:
            raise BusinessError("Cần có khách hàng trước khi tạo dữ liệu mock.")
        created_days = skipped_days = orders_created = 0
        cursor = start_on
        while cursor <= end_on:
            if self.mock_queries.daily_run(cursor):
                skipped_days += 1; cursor += timedelta(days=1); continue
            rng = Random(cursor.toordinal())
            available = list(self.mock_queries.fetch_seed_mock_range_legacy_available(volume_per_day))
            if len(available) < 2:
                raise BusinessError("Không đủ đĩa AVAILABLE để tạo mock.")
            created_for_day = 0
            for _ in range(volume_per_day):
                if len(available) < 2:
                    break
                count = min(rng.randint(2, 4), len(available))
                selected = [available.pop(rng.randrange(len(available))) for _index in range(count)]
                customer = customers[rng.randrange(len(customers))]
                lines = [
                    CheckoutLine(
                        copy.id,
                        LineAction.BUY if rng.random() < 0.20 else LineAction.RENT,
                        cursor + timedelta(days=3),
                    )
                    for copy in selected
                ]
                voucher_code = f"MOCKV{rng.randint(1, 20):02d}" if rng.random() < 0.35 else None
                quote = self.quote(customer.id, lines, voucher_code)
                order = self.checkout(
                    customer.id, actor_id,  lines,
                    [PaymentInput(PaymentMethod.CASH, quote.total_due)], voucher_code,
                )
                timestamp = datetime.combine(cursor, datetime.min.time(), tzinfo=timezone.utc) + timedelta(hours=10)
                order.created_at = order.updated_at = timestamp
                for payment in self.mock_queries.payments_for_order(order):
                    payment.created_at = payment.updated_at = timestamp
                if cursor < date.today():
                    terms = list(self.mock_queries.rentals_for_order(order))
                    if terms:
                        receipt = ReturnReceipt(customer_id=customer.id, employee_id=actor_id, returned_on=cursor + timedelta(days=3))
                        self.mock_queries.add_return_receipt(receipt); self.mock_queries.flush()
                        refund = Decimal("0")
                        for term in terms:
                            term.state, term.returned_on = RentalState.RETURNED, term.due_date
                            copy = self.mock_queries.get_physical_copy(term.line.copy_id)
                            if copy:
                                copy.status = CopyStatus.AVAILABLE
                            self.mock_queries.add_return_line(ReturnLine(receipt_id=receipt.id, rental_term_id=term.id, outcome='NORMAL'))
                            refund += Decimal(term.line.deposit_amount)
                        if refund:
                            self.mock_queries.add_payment_transaction(PaymentTransaction(order_id=order.id, customer_id=customer.id, employee_id=actor_id, method=PaymentMethod.CASH, category='DEPOSIT_REFUND', amount=-refund, note='Mock historical return', created_at=timestamp, updated_at=timestamp))
                created_for_day += 1
            self.mock_queries.add_mock_daily_run(MockDailyRun(business_date=cursor, seed_version='20260907', actor_id=actor_id, stats={'orders': created_for_day, 'volume': volume_per_day}))
            created_days += 1; orders_created += created_for_day; cursor += timedelta(days=1)
        self._audit(actor_id, "GENERATE_MOCK_RANGE", "MockDailyRun", f"{start_on}:{end_on}", {
            "created_days": created_days, "skipped_days": skipped_days, "orders": orders_created,
        })
        return MockSeedResult(created_days, skipped_days, orders_created)

    def seed_mock_range(
        self,
        start_on: date,
        end_on: date,
        actor_id: int,
        volume_per_day: int = 250,
    ) -> MockSeedResult:
        """Compatibility helper; the UI uses run_mock_seed for per-day commits."""
        if end_on < start_on or (end_on - start_on).days > 30:
            raise BusinessError("Khoảng mock tối đa 31 ngày.")
        fixtures = self.ensure_mock_fixtures(actor_id)
        created_days = skipped_days = orders_created = 0
        cursor = start_on
        while cursor <= end_on:
            if self.mock_queries.daily_run(cursor):
                skipped_days += 1
            else:
                orders_created += self.seed_mock_day(cursor, actor_id, volume_per_day)
                created_days += 1
            cursor += timedelta(days=1)
        return MockSeedResult(
            created_days, skipped_days, orders_created,
            combos_created=fixtures.combos_created,
            vouchers_created=fixtures.vouchers_created,
            memberships_created=fixtures.memberships_created,
        )

    def search_by_description_response(self, description: str) -> SearchResponse:
        if len(description.strip()) < 3:
            raise BusinessError("Hãy nhập mô tả ít nhất 3 ký tự.")
        return search_response(
            self.search_repository,
            description,
            self.gemini_api_key,
            self.gemini_embedding_model,
            self.gemini_embedding_dimensions,
            provider_factory=self.gemini_factory,
        )

    def search_by_description(self, description: str) -> list[SearchResult]:
        """Compatibility API for callers that only need the result rows."""
        return list(self.search_by_description_response(description).items)

    def operational_report(
        self,
        start_on: date | None = None,
        end_on: date | None = None,
    ) -> OperationalReport:
        return operational_report(self.reporting_repository.for_period(start_on, end_on), start_on=start_on, end_on=end_on)

    def chart_report(self, start_on: date | None, end_on: date | None,
                     action: LineAction | None = None, genre_id: int | None = None) -> ChartReport:
        if start_on and end_on and start_on > end_on:
            raise BusinessError("Ngày kết thúc không được trước ngày bắt đầu.")
        if action is not None and action not in (LineAction.RENT, LineAction.BUY):
            raise BusinessError("Loại giao dịch không hợp lệ.")
        repository = self.reporting_repository.for_period(start_on, end_on)
        return ChartReport(
            tuple((day, kind, Decimal(amount)) for day, kind, amount in repository.revenue_series(action, genre_id)),
            tuple((str(outcome), int(count)) for outcome, count in repository.damage_counts(action, genre_id)),
            tuple((str(name), int(count)) for name, count in repository.genre_sales(action, genre_id)),
        )

    def _status_history(self, copy: PhysicalCopy, before: CopyStatus | None, after: CopyStatus, note: str, actor_id: int | None = None) -> None:
        self.inventory_queries.add_copy_status_history(CopyStatusHistory(copy_id=copy.id, from_status=before, to_status=after, note=note, actor_id=actor_id))



