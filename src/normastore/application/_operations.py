from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from random import Random
from secrets import token_hex


from argon2 import PasswordHasher


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
from normastore.application.reporting import OperationalReport, operational_report
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
    late_fee,
    reputation_factor,
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
    ReputationEvent,
    Reservation,
    ReturnLine,
    ReturnReceipt,
    SaleReturn,
    Season,
    Shift,
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

    def open_shift(self, employee_id: int, opening_cash: Decimal) -> Shift:
        if opening_cash < 0:
            raise BusinessError("Tiền đầu ca không được âm.")
        employee = self.accounts.employee(employee_id)
        if not employee or not employee.active:
            raise BusinessError("Nhân viên không tồn tại hoặc đã ngưng hoạt động.")
        existing = self.accounts.current_shift(employee_id)
        if existing:
            return existing
        shift = Shift(employee_id=employee_id, opening_cash=opening_cash)
        self.accounts.save_shift(shift)
        self.accounts.add_audit(AuditLog(actor_id=employee_id, action="OPEN_SHIFT", entity="Shift", entity_id=str(shift.id), detail=str(opening_cash)))
        return shift

    def close_shift(self, shift_id: int, closing_cash: Decimal, actor_id: int) -> Shift:
        if closing_cash < 0:
            raise BusinessError("Tiền cuối ca không được âm.")
        shift = self.accounts.shift(shift_id)
        if not shift or shift.closed_at:
            raise BusinessError("Không tìm thấy ca đang mở.")
        if shift.employee_id != actor_id:
            self._require_manager(actor_id)
        shift.closed_at = datetime.now(timezone.utc)
        shift.closing_cash = closing_cash
        self.accounts.add_audit(AuditLog(actor_id=actor_id, action="CLOSE_SHIFT", entity="Shift", entity_id=str(shift.id), detail=str(closing_cash)))
        return shift

    def current_shift(self, employee_id: int) -> Shift | None:
        return self.accounts.current_shift(employee_id)

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

    def add_customer(self, full_name: str, phone: str, email: str = "", actor_id: int | None = None) -> Customer:
        if not full_name.strip() or not phone.strip():
            raise BusinessError("Tên và số điện thoại là bắt buộc.")
        if self.customers_queries.customer_by_phone(phone.strip()):
            raise BusinessError("Số điện thoại đã tồn tại.")
        customer = Customer(full_name=full_name.strip(), phone=phone.strip(), email=email.strip() or None)
        self.customers_queries.save_customer(customer)
        self._audit(actor_id, "CREATE_CUSTOMER", "Customer", customer.id, {"phone": customer.phone})
        return customer

    def adjust_reputation(self, customer_id: int, delta: int, reason: str, actor_id: int) -> Customer:
        self._require_manager(actor_id)
        customer = self.customers_queries.customer(customer_id)
        if not customer or not reason.strip() or delta == 0:
            raise BusinessError("Cần khách hàng, thay đổi điểm khác 0 và lý do.")
        before = customer.reputation_score
        customer.reputation_score = max(0, min(100, before + delta))
        actual_delta = customer.reputation_score - before
        if actual_delta:
            self.customers_queries.add_reputation_event(ReputationEvent(customer_id=customer.id, delta=actual_delta, reason=reason.strip(), actor_id=actor_id))
            self.accounts.add_audit(AuditLog(actor_id=actor_id, action="ADJUST_REPUTATION", entity="Customer", entity_id=str(customer.id), detail=reason.strip()))
        return customer

    def query_customers(self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec()) -> PagedResult[Customer]:
        return self.customers_queries.query_customers(text, page_request, sort)

    def list_customers(self, text: str = "") -> list[Customer]:
        return list(self.query_customers(text, PageRequest(1, 200)).items)

    def premium_active(self, customer_id: int, on_date: date | None = None) -> bool:
        on_date = on_date or date.today()
        return self.customers_queries.premium_active(customer_id, on_date)

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
        if not self.customers_queries.customer(customer_id):
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
        code: str,
        actor_id: int,
        percent_off: Decimal | None = None,
        amount_off: Decimal | None = None,
        starts_on: date | None = None,
        ends_on: date | None = None,
    ) -> Voucher:
        self._require_manager(actor_id)
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

    def choose_checkout_copy(
        self,
        item_id: int,
        action: LineAction,
        excluded_copy_ids: set[int] | None = None,
    ) -> CopyChoice | None:
        if action not in (LineAction.RENT, LineAction.BUY):
            raise BusinessError("Loại dòng phiếu không hợp lệ.")
        choice = self.catalog_queries.checkout_copy(item_id, action, excluded_copy_ids)
        if not choice:
            return None
        copy, item = choice
        price = copy.rental_price_override or item.rental_price if action == LineAction.RENT else copy.sale_price_override or item.sale_price
        return CopyChoice(copy.id, item.id, copy.barcode, item.title, action, Decimal(price))

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
                deposit_amount=Decimal("90000"),
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
        barcode: str,
        media_format: str = "DVD",
        actor_id: int | None = None,
        can_rent: bool | None = None,
        can_sell: bool | None = None,
    ) -> PhysicalCopy:
        if actor_id is None:
            raise BusinessError("Cần tài khoản quản lý để nhập kho.")
        self._require_manager(actor_id)
        item = self.catalog_item(item_id)
        if not barcode.strip():
            raise BusinessError("Barcode là bắt buộc.")
        if self.inventory_queries.fetch_add_copy_check(barcode):
            raise BusinessError("Barcode đã tồn tại.")
        rent_allowed = item.can_rent if can_rent is None else can_rent
        sell_allowed = item.can_sell if can_sell is None else can_sell
        if not rent_allowed and not sell_allowed:
            raise BusinessError("Bản đĩa phải cho phép thuê hoặc cho phép bán.")
        defaults = self.deposit_defaults()
        copy = PhysicalCopy(
            item_id=item.id,
            barcode=barcode.strip(),
            media_format=media_format,
            can_rent=rent_allowed,
            can_sell=sell_allowed,
            deposit_override=defaults.get(media_format, item.deposit_amount),
        )
        self.inventory_queries.add_physical_copy(copy)
        self.inventory_queries.flush()
        self._status_history(copy, None, CopyStatus.AVAILABLE, "Nhập kho", actor_id)
        self._audit(actor_id, "ADD_COPY", "PhysicalCopy", copy.id, {
            "barcode": copy.barcode, "format": copy.media_format,
            "can_rent": copy.can_rent, "can_sell": copy.can_sell,
        })
        return copy

    def deposit_defaults(self) -> dict[str, Decimal]:
        fallback = {
            "VHS": Decimal("80000"), "VCD": Decimal("100000"),
            "DVD": Decimal("150000"), "Blu-ray": Decimal("250000"),
        }
        saved = {row.media_format: Decimal(row.amount) for row in self.inventory_queries.deposit_defaults()}
        return fallback | saved

    def save_deposit_defaults(self, values: dict[str, Decimal], actor_id: int) -> dict[str, Decimal]:
        self._require_manager(actor_id)
        required = {"VHS", "VCD", "DVD", "Blu-ray"}
        if set(values) != required or any(Decimal(amount) < 0 for amount in values.values()):
            raise BusinessError("Cần nhập mức cọc không âm cho VHS, VCD, DVD và Blu-ray.")
        existing = {row.media_format: row for row in self.inventory_queries.deposit_defaults()}
        before = self.deposit_defaults()
        for media_format, amount in values.items():
            row = existing.get(media_format)
            if row is None:
                self.inventory_queries.add_deposit_default(DepositDefault(media_format=media_format, amount=Decimal(amount), updated_by=actor_id))
            else:
                row.amount, row.updated_by = Decimal(amount), actor_id
        self._audit(actor_id, "UPDATE_DEPOSIT_DEFAULTS", "DepositDefault", "all", {
            "before": {key: str(value) for key, value in before.items()},
            "after": {key: str(Decimal(value)) for key, value in values.items()},
        })
        return {key: Decimal(value) for key, value in values.items()}

    def apply_deposit_defaults_to_inventory(self, actor_id: int) -> int:
        self._require_manager(actor_id)
        defaults = self.deposit_defaults()
        copies = list(self.inventory_queries.fetch_apply_deposit_defaults_to_inventory_copies())
        for copy in copies:
            copy.deposit_override = defaults.get(copy.media_format, defaults["DVD"])
        self._audit(actor_id, "APPLY_DEPOSIT_DEFAULTS", "PhysicalCopy", "all", {
            "copies": len(copies), "formats": {key: str(value) for key, value in defaults.items()},
        })
        return len(copies)

    def update_inventory_copy(
        self, copy_id: int, request: UpdateInventoryCopyRequest, actor_id: int
    ) -> PhysicalCopy:
        self._require_manager(actor_id)
        if not request.barcode.strip() or not (request.can_rent or request.can_sell):
            raise BusinessError("Cần barcode và ít nhất một quyền thuê/bán.")
        if any(value is not None and value < 0 for value in (
            request.rental_price_override, request.sale_price_override, request.deposit_override,
        )):
            raise BusinessError("Giá override và tiền cọc không được âm.")
        copy = self.inventory_queries.lock_copy(copy_id)
        if not copy:
            raise BusinessError("Không tìm thấy bản đĩa.")
        if self.inventory_queries.fetch_update_inventory_copy_check(copy_id, request):
            raise BusinessError("Barcode đã tồn tại.")
        safe_statuses = {CopyStatus.AVAILABLE, CopyStatus.INSPECTION, CopyStatus.REPAIR, CopyStatus.LOST, CopyStatus.RETIRED}
        if request.status not in safe_statuses:
            raise BusinessError("Trạng thái giao dịch chỉ được đổi qua nghiệp vụ thuê, bán hoặc giữ chỗ.")
        if copy.status not in safe_statuses and request.status != copy.status:
            raise BusinessError("Không thể ép đổi trạng thái của đĩa đang thuê, giữ chỗ hoặc đã bán.")
        if copy.status != request.status and not request.note.strip():
            raise BusinessError("Cần ghi chú khi đổi trạng thái kho.")
        before = {
            "barcode": copy.barcode, "format": copy.media_format, "condition": copy.condition.value,
            "status": copy.status.value, "can_rent": copy.can_rent, "can_sell": copy.can_sell,
        }
        old_status = copy.status
        copy.barcode = request.barcode.strip()
        copy.media_format = request.media_format
        copy.condition = request.condition
        copy.can_rent, copy.can_sell = request.can_rent, request.can_sell
        copy.rental_price_override = request.rental_price_override
        copy.sale_price_override = request.sale_price_override
        copy.deposit_override = request.deposit_override
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
        deposit_amount: Decimal | None = None,
    ) -> int:
        self._require_manager(actor_id)
        changes = {key: value for key, value in {"rental_price": rental_price, "sale_price": sale_price, "deposit_amount": deposit_amount}.items() if value is not None}
        if not item_ids or not changes or any(value < 0 for value in changes.values()):
            raise BusinessError("Cần chọn item và nhập giá trị không âm để sửa hàng loạt.")
        items = list(self.inventory_queries.fetch_bulk_update_catalog_prices_items(item_ids))
        for item in items:
            for key, value in changes.items():
                setattr(item, key, value)
            self.inventory_queries.add_audit_log(AuditLog(actor_id=actor_id, action='BULK_PRICE_EDIT', entity='CatalogItem', entity_id=str(item.id), detail=','.join(changes)))
        return len(items)

    def _customer_limit(self, customer: Customer) -> int:
        _factor, adjustment, manager_required = reputation_factor(customer.reputation_score)
        limit = (8 if self.premium_active(customer.id) else 4) + adjustment
        return max(1, limit if not manager_required else 1)

    def _require_manager(self, employee_id: int) -> None:
        role_code = self.accounts.role_for_employee(employee_id)
        if role_code not in (RoleCode.ADMIN, RoleCode.MANAGER):
            raise BusinessError("Thao tác này cần quyền Quản lý hoặc Quản trị viên.")

    def _open_rental_count(self, customer_id: int) -> int:
        return int(self.orders_queries.fetch_open_rental_count_rows(customer_id) or 0)

    def quote(self, customer_id: int, lines: list[CheckoutLine], voucher_code: str | None = None, combo_ids: list[int] | None = None) -> Quote:
        if not lines:
            raise BusinessError("Phiếu chưa có bản đĩa nào.")
        customer = self.orders_queries.get_customer(customer_id)
        if not customer:
            raise BusinessError("Không tìm thấy khách hàng.")
        copies = list(self.orders_queries.fetch_quote_copies(lines))
        if len(copies) != len({line.copy_id for line in lines}):
            raise BusinessError("Có bản đĩa không tồn tại.")
        by_id = {copy.id: copy for copy in copies}
        rent_count = sum(line.action == LineAction.RENT for line in lines)
        if self._open_rental_count(customer_id) + rent_count > self._customer_limit(customer):
            raise BusinessError("Khách đã vượt giới hạn số đĩa được thuê.")
        gross = Decimal("0")
        deposit = Decimal("0")
        line_prices: dict[int, Decimal] = {}
        premium = self.premium_active(customer_id)
        for line in lines:
            copy = by_id[line.copy_id]
            if copy.status != CopyStatus.AVAILABLE:
                raise BusinessError(f"{copy.barcode} không còn sẵn sàng.")
            if line.action == LineAction.RENT:
                if not copy.can_rent or not copy.item.can_rent or not line.due_date:
                    raise BusinessError("Dòng thuê cần hạn trả và bản đĩa cho phép thuê.")
                price = copy.rental_price_override or copy.item.rental_price
                deposit += effective_deposit(copy.deposit_override or copy.item.deposit_amount, premium, customer.reputation_score)
            elif line.action == LineAction.BUY:
                if not copy.can_sell or not copy.item.can_sell:
                    raise BusinessError("Bản đĩa không cho phép bán.")
                price = copy.sale_price_override or copy.item.sale_price
            else:
                raise BusinessError("Loại dòng phiếu không hợp lệ.")
            line_prices[copy.id] = Decimal(price)
            gross += Decimal(price)
        selected_item_ids = {copy.item_id for copy in copies}
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
        combo_discount = min(combo_discount, gross)
        premium_discount = (gross - combo_discount) * Decimal("0.10") if premium else Decimal("0")
        voucher_discount = Decimal("0")
        if voucher_code:
            voucher = self.promotions.active_voucher(voucher_code.strip().upper())
            if not voucher:
                raise BusinessError("Voucher không hợp lệ.")
            today = date.today()
            if (voucher.starts_on and voucher.starts_on > today) or (voucher.ends_on and voucher.ends_on < today):
                raise BusinessError("Voucher chưa có hiệu lực hoặc đã hết hạn.")
            if voucher.percent_off:
                voucher_discount = (gross - combo_discount - premium_discount) * Decimal(voucher.percent_off) / Decimal("100")
            elif voucher.amount_off:
                voucher_discount = Decimal(voucher.amount_off)
        discount_cap = gross * Decimal("0.50")
        combo_discount = min(combo_discount, discount_cap)
        premium_discount = min(premium_discount, discount_cap - combo_discount)
        voucher_discount = min(voucher_discount, discount_cap - combo_discount - premium_discount)
        discount = combo_discount + premium_discount + voucher_discount
        sources = {source: value for source, value in {"COMBO": combo_discount, "PREMIUM": premium_discount, "VOUCHER": voucher_discount}.items() if value}
        source_codes = {
            "COMBO": ",".join(map(str, applied_combo_ids)) or None,
            "VOUCHER": voucher_code.strip().upper() if voucher_code and voucher_discount else None,
            "PREMIUM": None,
        }
        return Quote(gross, discount, deposit, gross - discount + deposit, line_prices, sources, source_codes)

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
    ) -> Order:
        if any(Decimal(payment.amount) < 0 for payment in payments):
            raise BusinessError("Khoản thanh toán không được âm.")
        quote = self.quote(customer_id, lines, voucher_code, combo_ids)
        locked = list(self.orders_queries.fetch_checkout_locked(lines))
        by_id = {copy.id: copy for copy in locked}
        if any(copy.status != CopyStatus.AVAILABLE for copy in locked):
            raise BusinessError("Tồn kho đã thay đổi, hãy lập lại phiếu.")
        code = order_code or f"PX{datetime.now():%y%m%d%H%M%S}{token_hex(4).upper()}"
        if self.orders_queries.fetch_checkout_check(code):
            raise BusinessError("Mã phiếu đã tồn tại.")
        order = Order(code=code, customer_id=customer_id, employee_id=employee_id, shift_id=shift_id,
                      gross_total=quote.gross, discount_total=quote.discount, deposit_total=quote.deposit)
        self.orders_queries.add_order(order)
        self.orders_queries.flush()
        for source, amount in quote.discount_sources.items():
            self.orders_queries.add_order_discount(OrderDiscount(order_id=order.id, source=source, amount=amount, source_code=quote.discount_source_codes.get(source)))
        customer = self.orders_queries.get_customer(customer_id)
        assert customer is not None
        premium = self.premium_active(customer_id)
        discounts_by_copy: dict[int, Decimal] = {}
        remaining_discount = quote.discount
        for index, request in enumerate(lines):
            if index == len(lines) - 1:
                discounts_by_copy[request.copy_id] = remaining_discount
                continue
            share = (quote.line_prices[request.copy_id] * quote.discount / quote.gross).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP
            )
            discounts_by_copy[request.copy_id] = min(share, remaining_discount)
            remaining_discount -= discounts_by_copy[request.copy_id]
        for request in lines:
            copy = by_id[request.copy_id]
            price = quote.line_prices[copy.id]
            deposit = Decimal("0")
            if request.action == LineAction.RENT:
                deposit = effective_deposit(copy.deposit_override or copy.item.deposit_amount, premium, customer.reputation_score)
            line = OrderLine(order_id=order.id, copy_id=copy.id, action=request.action, title_snapshot=copy.item.title,
                             unit_price=price, discount_amount=discounts_by_copy[copy.id], deposit_amount=deposit)
            self.orders_queries.add_order_line(line)
            self.orders_queries.flush()
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

    def query_active_rentals(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("due", False)) -> PagedResult[ActiveRental]:
        return self.orders_queries.query_active_rentals(page_request, sort)

    def active_rentals(self) -> list[ActiveRental]:
        return list(self.query_active_rentals(PageRequest(1, 10_000)).items)

    def query_orders(self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created_at", True)) -> PagedResult[OrderSummary]:
        return self.orders_queries.query_orders(text, page_request, sort)

    def list_orders(self, text: str = "", limit: int = 200) -> list[OrderSummary]:
        return list(self.query_orders(text, PageRequest(1, limit)).items)

    def order_detail(self, order_id: int) -> tuple[OrderSummary, list[OrderDetailLine]]:
        order, customer, employee = self.orders_queries.order_with_parties(order_id).one_or_none() or (None, None, None)
        if not order:
            raise BusinessError("Không tìm thấy phiếu.")
        lines = self.orders_queries.order_lines_with_copies(order_id).all()
        summary = OrderSummary(order.id, order.code, customer.full_name, employee.full_name, order.created_at, order.status, Decimal(order.gross_total) - Decimal(order.discount_total) + Decimal(order.deposit_total))
        return summary, [
            OrderDetailLine(
                title=line.title_snapshot,
                barcode=copy.barcode if copy else None,
                action=line.action,
                unit_price=Decimal(line.unit_price),
                deposit=Decimal(line.deposit_amount),
                due_date=term.due_date if term else None,
                rental_state=term.state if term else None,
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
            (payment.amount for payment in payments if payment.category == "CHECKOUT"), Decimal("0")
        )
        total_due = Decimal(order.gross_total) - Decimal(order.discount_total) + Decimal(order.deposit_total)
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
            discount_total=Decimal(order.discount_total),
            deposit_total=Decimal(order.deposit_total),
            total_due=total_due,
            checkout_paid=checkout_paid,
            balance_due=max(Decimal("0"), total_due - checkout_paid),
            lines=tuple(
                OrderReceiptLine(
                    title=line.title_snapshot,
                    barcode=copy.barcode if copy else None,
                    action=line.action,
                    unit_price=Decimal(line.unit_price),
                    discount_amount=Decimal(line.discount_amount),
                    net_amount=Decimal(line.unit_price) - Decimal(line.discount_amount),
                    deposit=Decimal(line.deposit_amount),
                    due_date=term.due_date if term else None,
                    rental_state=term.state.value if term else None,
                )
                for line, copy, term in line_rows
            ),
            discounts=discounts,
            payments=payments,
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

    def return_rentals(self, employee_id: int, customer_id: int, returns: list[tuple[int, ReturnOutcome, str]], payment: PaymentInput | None = None, today: date | None = None) -> Decimal:
        today = today or date.today()
        receipt = ReturnReceipt(customer_id=customer_id, employee_id=employee_id, returned_on=today)
        self.orders_queries.add_return_receipt(receipt)
        self.orders_queries.flush()
        balance = Decimal("0")
        returned_item_ids: set[int] = set()
        for term_id, outcome, note in returns:
            term = self.orders_queries.fetch_return_rentals_term(term_id)
            if not term or term.state != RentalState.ACTIVE:
                raise BusinessError("Dòng thuê không còn hoạt động.")
            if term.line.order.customer_id != customer_id:
                raise BusinessError("Dòng thuê không thuộc khách hàng đang trả.")
            copy = term.line.copy
            assert copy is not None
            late = late_fee(term.due_date, today, Decimal(term.late_daily_rate))
            damage = damage_fee(copy.item.replacement_value, outcome)
            charges = late + damage
            if late:
                self.orders_queries.add_penalty_charge(PenaltyCharge(rental_term_id=term.id, kind='LATE', amount=late, reason='Trả quá hạn'))
            if damage:
                self.orders_queries.add_penalty_charge(PenaltyCharge(rental_term_id=term.id, kind=outcome.value, amount=damage, reason=note or outcome.value))
            deposit = Decimal(term.line.deposit_amount)
            balance += charges - deposit
            before = copy.status
            if outcome == ReturnOutcome.NORMAL:
                copy.status = CopyStatus.AVAILABLE
                copy.condition = CopyCondition.GOOD
                returned_item_ids.add(copy.item_id)
            elif outcome in (ReturnOutcome.LIGHT_DAMAGE, ReturnOutcome.HEAVY_DAMAGE):
                copy.status = CopyStatus.REPAIR
                copy.condition = CopyCondition.DAMAGED
            else:
                copy.status = CopyStatus.LOST
                term.state = RentalState.LOST
            if term.state != RentalState.LOST:
                term.state = RentalState.RETURNED
            term.returned_on = today
            self.orders_queries.add_return_line(ReturnLine(receipt_id=receipt.id, rental_term_id=term.id, outcome=outcome.value, note=note or None))
            self._status_history(copy, before, copy.status, f"Trả đĩa: {outcome.value}", employee_id)
        for item_id in returned_item_ids:
            self.allocate_waiting_reservations(item_id)
        if balance < 0:
            self.orders_queries.add_payment_transaction(PaymentTransaction(customer_id=customer_id, employee_id=employee_id, method=PaymentMethod.CASH, category='DEPOSIT_REFUND', amount=balance))
        elif payment:
            amount = Decimal(payment.amount)
            if amount < 0 or amount > balance:
                raise BusinessError("Khoản thu thêm không hợp lệ.")
            if amount:
                self.orders_queries.add_payment_transaction(PaymentTransaction(customer_id=customer_id, employee_id=employee_id, method=payment.method, category='RETURN_SETTLEMENT', amount=amount))
        self._audit(employee_id, "RETURN_RENTAL", "ReturnReceipt", receipt.id, {
            "customer_id": customer_id, "lines": len(returns), "balance": str(balance),
        })
        return balance

    def extend_rental(self, rental_term_id: int, employee_id: int, days: int = 3) -> RentalTerm:
        term = self.orders_queries.fetch_extend_rental_term(rental_term_id)
        if not term or term.state != RentalState.ACTIVE:
            raise BusinessError("Chỉ có thể gia hạn dòng thuê đang hoạt động.")
        if days != 3:
            raise BusinessError("Mỗi lần gia hạn chuẩn là 3 ngày.")
        has_waiting_reservation = self.orders_queries.fetch_extend_rental_has_waiting_reservation(term) is not None
        if term.due_date < date.today() or has_waiting_reservation:
            self._require_manager(employee_id)
        old_due_date = term.due_date
        term.due_date += timedelta(days=days)
        copy = term.line.copy
        assert copy is not None
        self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=term.line.order_id, customer_id=self.orders_queries.get_order(term.line.order_id).customer_id, employee_id=employee_id, method=PaymentMethod.CASH, category='RENTAL_EXTENSION', amount=copy.rental_price_override or copy.item.rental_price))
        self.orders_queries.add_rental_extension(RentalExtension(rental_term_id=term.id, old_due_date=old_due_date, new_due_date=term.due_date, fee=copy.rental_price_override or copy.item.rental_price, employee_id=employee_id))
        self._audit(employee_id, "EXTEND_RENTAL", "RentalTerm", term.id, {"days": days, "due_date": str(term.due_date)})
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
        sale_price = Decimal(copy.sale_price_override or copy.item.sale_price)
        applied_deposit = min(Decimal(source.deposit_amount), sale_price)
        sale = Order(
            code=f"PB{datetime.now():%y%m%d%H%M%S}{token_hex(2).upper()}",
            customer_id=order.customer_id,
            employee_id=employee_id,
            shift_id=order.shift_id,
            gross_total=sale_price,
            discount_total=applied_deposit,
            deposit_total=Decimal("0"),
        )
        self.orders_queries.add_order(sale)
        self.orders_queries.flush()
        self.orders_queries.add_order_line(OrderLine(order_id=sale.id, copy_id=copy.id, action=LineAction.BUY, title_snapshot=copy.item.title, unit_price=sale_price, discount_amount=applied_deposit, source_rental_line_id=source.id))
        term.state = RentalState.PURCHASED
        before = copy.status
        copy.status = CopyStatus.SOLD
        self._status_history(copy, before, copy.status, f"Chuyển thuê thành mua: {sale.code}", employee_id)
        self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=sale.id, customer_id=order.customer_id, employee_id=employee_id, method=payment.method, category='RENTAL_TO_SALE', amount=payment.amount))
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
                sold_on=order.created_at.date(),
                expires_on=order.created_at.date() + timedelta(days=7),
            )
            for line, order, customer, copy in rows
            if sale_return_allowed(order.created_at.date(), today)
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
        if not line or not sale_return_allowed(line.order.created_at.date(), today):
            raise BusinessError("Dòng bán không còn trong thời hạn hoàn trả 7 ngày.")
        copy = line.copy
        if not copy or copy.status != CopyStatus.SOLD:
            raise BusinessError("Bản đĩa này không ở trạng thái đã bán.")
        if condition not in (CopyCondition.GOOD, CopyCondition.WORN, CopyCondition.DAMAGED):
            raise BusinessError("Tình trạng đĩa hoàn không hợp lệ.")
        if condition != CopyCondition.GOOD:
            self._require_manager(employee_id)
        gross_refund = Decimal(line.unit_price) - Decimal(line.discount_amount)
        deduction = Decimal(deduction)
        if deduction < 0 or deduction > gross_refund:
            raise BusinessError("Mức khấu trừ hoàn hàng không hợp lệ.")
        refund = gross_refund - deduction
        copy.condition = condition
        copy.status = CopyStatus.INSPECTION
        status_note = note.strip() or "Khách trả hàng bán"
        if deduction:
            status_note = f"{status_note}; khấu trừ {deduction:,.0f}"
        self._status_history(copy, CopyStatus.SOLD, CopyStatus.INSPECTION, status_note, employee_id)
        self.orders_queries.add_payment_transaction(PaymentTransaction(order_id=line.order_id, customer_id=line.order.customer_id, employee_id=employee_id, method=PaymentMethod.CASH, category='SALE_REFUND', amount=-refund))
        self.orders_queries.add_sale_return(SaleReturn(sale_line_id=line.id, employee_id=employee_id, returned_on=today, refund_amount=refund, note=status_note))
        self._audit(employee_id, "RETURN_SALE", "SaleReturn", line.id, {"refund": str(refund), "condition": condition.value})
        return refund

    def query_inventory(self, status: CopyStatus | None = None, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("title")) -> PagedResult[InventoryCopy]:
        return self.inventory_queries.query_inventory(status, page_request, sort)

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
        if target_status == CopyStatus.AVAILABLE:
            copy.condition = CopyCondition.GOOD
        elif target_status == CopyStatus.REPAIR:
            copy.condition = CopyCondition.DAMAGED
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

    def query_reservations(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created", True)) -> PagedResult[ReservationView]:
        return self.reservations_queries.query_reservations(page_request, sort)

    def list_reservations(self) -> list[ReservationView]:
        return list(self.query_reservations(PageRequest(1, 10_000)).items)

    def expire_reservation_holds(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        reservations = list(
            self.reservations_queries.fetch_expire_reservation_holds_reservations(now)
        )
        item_ids: set[int] = set()
        for reservation in reservations:
            copy = self.reservations_queries.fetch_expire_reservation_holds_copy(reservation)
            if copy and copy.status == CopyStatus.HELD:
                copy.status = CopyStatus.AVAILABLE
                self._status_history(copy, CopyStatus.HELD, CopyStatus.AVAILABLE, "Hết hạn giữ chỗ")
            reservation.state = ReservationState.EXPIRED
            item_ids.add(reservation.item_id)
        for item_id in item_ids:
            self.allocate_waiting_reservations(item_id)
        return len(reservations)

    def allocate_waiting_reservations(self, item_id: int) -> int:
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
        return count

    def dashboard(self) -> dict[str, Decimal | int]:
        today = date.today()
        rented = self.dashboard_queries.fetch_dashboard_rented() or 0
        available = self.dashboard_queries.fetch_dashboard_available() or 0
        overdue = self.dashboard_queries.fetch_dashboard_overdue(today) or 0
        held = self.dashboard_queries.fetch_dashboard_held() or 0
        cash_flow = self.dashboard_queries.fetch_dashboard_cash_flow() or Decimal("0")
        return {"available": available, "rented": rented, "overdue": overdue, "reservations": held, "cash_flow": Decimal(cash_flow)}

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
        premium_ids = set(self.mock_queries.fetch_seed_mock_day_premium_ids(business_date))
        open_counts = dict(self.mock_queries.fetch_seed_mock_day_open_counts().all())
        rng = Random(business_date.toordinal())

        def limit(customer: Customer) -> int:
            _factor, adjustment, manager_required = reputation_factor(customer.reputation_score)
            return 1 if manager_required else max(1, (8 if customer.id in premium_ids else 4) + adjustment)

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
            rent_count = sum(item == LineAction.RENT for item in actions)
            eligible = [customer for customer in customers if open_counts.get(customer.id, 0) + rent_count <= limit(customer)]
            if not eligible:
                raise BusinessError("Không còn khách phù hợp với hạn mức thuê.")
            customer = eligible[rng.randrange(len(eligible))]
            lines = [CheckoutLine(copy.id, choice, business_date + timedelta(days=3) if choice == LineAction.RENT else None) for copy, choice in zip(selected, actions, strict=True)]
            voucher = active_vouchers[rng.randrange(len(active_vouchers))] if active_vouchers and rng.random() < 0.35 else None
            quote = self.quote(customer.id, lines, voucher, [combo_id] if combo_id else None)
            order = self.checkout(customer.id, actor_id, None, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)], voucher, [combo_id] if combo_id else None, order_code=f"MOCK-{business_date:%Y%m%d}-{number:03d}")
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
            else:
                open_counts[customer.id] = open_counts.get(customer.id, 0) + rent_count
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
                    customer.id, actor_id, None, lines,
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

    def _status_history(self, copy: PhysicalCopy, before: CopyStatus | None, after: CopyStatus, note: str, actor_id: int | None = None) -> None:
        self.inventory_queries.add_copy_status_history(CopyStatusHistory(copy_id=copy.id, from_status=before, to_status=after, note=note, actor_id=actor_id))



