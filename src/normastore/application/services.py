from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from random import Random
from secrets import token_hex
from typing import Callable

from argon2 import PasswordHasher
from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

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
from normastore.infrastructure.database import (
    AuditLog,
    CatalogItem,
    Combo,
    ComboItem,
    CopyStatusHistory,
    Customer,
    DepositDefault,
    Employee,
    ExternalReview,
    Genre,
    ItemGenre,
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
    Role,
    SaleReturn,
    Season,
    Shift,
    Show,
    UserAccount,
    Voucher,
)
from normastore.jobs import scheduled_reminders


class BusinessError(ValueError):
    pass


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


class StoreService:
    def __init__(
        self,
        session: Session,
        gemini_api_key: str | None = None,
        gemini_embedding_model: str = "gemini-embedding-001",
        gemini_embedding_dimensions: int = 768,
        gemini_generation_model: str = "gemini-3.5-flash-lite",
    ):
        self.session = session
        self.gemini_api_key = gemini_api_key
        self.gemini_embedding_model = gemini_embedding_model
        self.gemini_embedding_dimensions = gemini_embedding_dimensions
        self.gemini_generation_model = gemini_generation_model
        self.password_hasher = PasswordHasher()

    def _audit(
        self,
        actor_id: int | None,
        action: str,
        entity: str,
        entity_id: int | str,
        detail: dict | str | None = None,
    ) -> None:
        self.session.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                entity=entity,
                entity_id=str(entity_id),
                detail=detail,
            )
        )

    def _page_rows(self, stmt, page_request: PageRequest) -> PagedResult:
        total_items = int(self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
        page_size = max(1, min(page_request.page_size, 10_000))
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = min(max(1, page_request.page), total_pages)
        rows = tuple(self.session.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all())
        return PagedResult(rows, page, page_size, total_items, total_pages)

    def authenticate(self, username: str, password: str) -> UserAccount | None:
        account = self.session.scalar(
            select(UserAccount).options(joinedload(UserAccount.employee), joinedload(UserAccount.role)).where(
                UserAccount.username == username.strip()
            )
        )
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
        account = self.session.get(UserAccount, account_id)
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
        employee = self.session.get(Employee, employee_id)
        if not employee or not employee.active:
            raise BusinessError("Nhân viên không tồn tại hoặc đã ngưng hoạt động.")
        existing = self.session.scalar(select(Shift).where(Shift.employee_id == employee_id, Shift.closed_at.is_(None)))
        if existing:
            return existing
        shift = Shift(employee_id=employee_id, opening_cash=opening_cash)
        self.session.add(shift)
        self.session.flush()
        self.session.add(AuditLog(actor_id=employee_id, action="OPEN_SHIFT", entity="Shift", entity_id=str(shift.id), detail=str(opening_cash)))
        return shift

    def close_shift(self, shift_id: int, closing_cash: Decimal, actor_id: int) -> Shift:
        if closing_cash < 0:
            raise BusinessError("Tiền cuối ca không được âm.")
        shift = self.session.get(Shift, shift_id)
        if not shift or shift.closed_at:
            raise BusinessError("Không tìm thấy ca đang mở.")
        if shift.employee_id != actor_id:
            self._require_manager(actor_id)
        shift.closed_at = datetime.now(timezone.utc)
        shift.closing_cash = closing_cash
        self.session.add(AuditLog(actor_id=actor_id, action="CLOSE_SHIFT", entity="Shift", entity_id=str(shift.id), detail=str(closing_cash)))
        return shift

    def current_shift(self, employee_id: int) -> Shift | None:
        return self.session.scalar(select(Shift).where(Shift.employee_id == employee_id, Shift.closed_at.is_(None)))

    def list_employees(self) -> list[EmployeeSummary]:
        rows = self.session.execute(
            select(Employee, UserAccount, Role)
            .outerjoin(UserAccount, UserAccount.employee_id == Employee.id)
            .outerjoin(Role, UserAccount.role_id == Role.id)
            .order_by(Employee.full_name)
        ).all()
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
        if self.session.scalar(select(UserAccount.id).where(UserAccount.username == username.strip())):
            raise BusinessError("Tên đăng nhập đã tồn tại.")
        role = self.session.scalar(select(Role).where(Role.code == role_code))
        if not role:
            raise BusinessError("Vai trò chưa được khởi tạo.")
        employee = Employee(full_name=full_name.strip(), phone=phone.strip() or None)
        self.session.add(employee)
        self.session.flush()
        self.session.add(UserAccount(employee_id=employee.id, role_id=role.id, username=username.strip(), password_hash=self.password_hasher.hash(password)))
        self._audit(actor_id, "CREATE_EMPLOYEE", "Employee", employee.id, {"username": username.strip(), "role": role_code.value})
        return employee

    def add_customer(self, full_name: str, phone: str, email: str = "", actor_id: int | None = None) -> Customer:
        if not full_name.strip() or not phone.strip():
            raise BusinessError("Tên và số điện thoại là bắt buộc.")
        if self.session.scalar(select(Customer).where(Customer.phone == phone.strip())):
            raise BusinessError("Số điện thoại đã tồn tại.")
        customer = Customer(full_name=full_name.strip(), phone=phone.strip(), email=email.strip() or None)
        self.session.add(customer)
        self.session.flush()
        self._audit(actor_id, "CREATE_CUSTOMER", "Customer", customer.id, {"phone": customer.phone})
        return customer

    def adjust_reputation(self, customer_id: int, delta: int, reason: str, actor_id: int) -> Customer:
        self._require_manager(actor_id)
        customer = self.session.get(Customer, customer_id)
        if not customer or not reason.strip() or delta == 0:
            raise BusinessError("Cần khách hàng, thay đổi điểm khác 0 và lý do.")
        before = customer.reputation_score
        customer.reputation_score = max(0, min(100, before + delta))
        actual_delta = customer.reputation_score - before
        if actual_delta:
            self.session.add(ReputationEvent(customer_id=customer.id, delta=actual_delta, reason=reason.strip(), actor_id=actor_id))
            self.session.add(AuditLog(actor_id=actor_id, action="ADJUST_REPUTATION", entity="Customer", entity_id=str(customer.id), detail=reason.strip()))
        return customer

    def query_customers(self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec()) -> PagedResult[Customer]:
        stmt = select(Customer).order_by(Customer.full_name)
        if text.strip():
            pattern = f"%{text.strip()}%"
            stmt = stmt.where((Customer.full_name.like(pattern)) | (Customer.phone.like(pattern)))
        fields = {"title": Customer.full_name, "phone": Customer.phone, "email": Customer.email, "trust": Customer.reputation_score}
        expression = fields.get(sort.field, Customer.full_name)
        stmt = stmt.order_by(None).order_by(desc(expression) if sort.descending else expression.asc(), Customer.id)
        page = self._page_rows(stmt, page_request)
        return PagedResult(tuple(row[0] for row in page.items), page.page, page.page_size, page.total_items, page.total_pages)

    def list_customers(self, text: str = "") -> list[Customer]:
        return list(self.query_customers(text, PageRequest(1, 200)).items)

    def premium_active(self, customer_id: int, on_date: date | None = None) -> bool:
        on_date = on_date or date.today()
        return self.session.scalar(
            select(PremiumMembership.id).where(
                PremiumMembership.customer_id == customer_id,
                PremiumMembership.starts_on <= on_date,
                PremiumMembership.ends_on >= on_date,
            )
        ) is not None

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
        if not self.session.get(Customer, customer_id):
            raise BusinessError("Không tìm thấy khách hàng.")
        membership = PremiumMembership(
            customer_id=customer_id, starts_on=date.today(), ends_on=date.today() + timedelta(days=days - 1),
            price_paid=prices[days],
        )
        self.session.add(membership)
        self.session.add(
            PaymentTransaction(
                customer_id=customer_id,
                employee_id=employee_id,
                method=method,
                category="PREMIUM",
                amount=prices[days],
            )
        )
        self.session.flush()
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
        if self.session.scalar(select(Voucher.id).where(Voucher.code == code)):
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
        self.session.add(voucher)
        self.session.flush()
        self._audit(actor_id, "CREATE_VOUCHER", "Voucher", voucher.id, {"code": voucher.code})
        return voucher

    def list_vouchers(self, include_inactive: bool = True, today: date | None = None) -> list[VoucherSummary]:
        today = today or date.today()
        statement = select(Voucher)
        if not include_inactive:
            statement = statement.where(Voucher.active.is_(True))
        vouchers = self.session.scalars(statement.order_by(Voucher.code)).all()

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
        found = self.session.scalars(select(CatalogItem.id).where(CatalogItem.id.in_(normalized_ids), CatalogItem.archived.is_(False))).all()
        if len(found) != len(normalized_ids):
            raise BusinessError("Combo có item không tồn tại hoặc đã lưu trữ.")
        combo = Combo(name=name.strip(), rule_type="FIXED", discount_amount=discount_amount)
        self.session.add(combo)
        self.session.flush()
        self.session.add_all([ComboItem(combo_id=combo.id, item_id=item_id) for item_id in normalized_ids])
        self._audit(actor_id, "CREATE_COMBO", "Combo", combo.id, {"name": combo.name, "items": normalized_ids})
        return combo

    def create_show_episode_combo(self, name: str, show_id: int, required_count: int, discount_amount: Decimal, actor_id: int) -> Combo:
        self._require_manager(actor_id)
        if not name.strip() or required_count < 2 or discount_amount <= 0:
            raise BusinessError("Combo cần tên, từ 2 tập trở lên và mức giảm lớn hơn 0.")
        show = self.session.get(Show, show_id)
        if not show or show.archived:
            raise BusinessError("Không tìm thấy bộ phim cho combo.")
        combo = Combo(
            name=name.strip(),
            rule_type="EPISODE_SHOW",
            show_id=show_id,
            required_count=required_count,
            discount_amount=discount_amount,
        )
        self.session.add(combo)
        self.session.flush()
        self._audit(actor_id, "CREATE_COMBO", "Combo", combo.id, {"name": combo.name, "show_id": show_id, "required_count": required_count})
        return combo

    def list_combos(self, include_inactive: bool = False) -> list[ComboSummary]:
        item_counts = (
            select(ComboItem.combo_id.label("combo_id"), func.count(ComboItem.item_id).label("item_count"))
            .group_by(ComboItem.combo_id)
            .subquery()
        )
        statement = (
            select(Combo, Show.title, func.coalesce(item_counts.c.item_count, 0))
            .outerjoin(Show, Combo.show_id == Show.id)
            .outerjoin(item_counts, item_counts.c.combo_id == Combo.id)
            .order_by(Combo.name)
        )
        if not include_inactive:
            statement = statement.where(Combo.active.is_(True))
        rows = self.session.execute(statement).all()
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

    def _catalog_statement(self, filters: CatalogFilters):
        rentable = func.coalesce(
            func.sum(case((and_(
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                PhysicalCopy.can_rent.is_(True),
                CatalogItem.can_rent.is_(True),
            ), 1), else_=0)),
            0,
        ).label("rentable_copies")
        sellable = func.coalesce(
            func.sum(case((and_(
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                PhysicalCopy.can_sell.is_(True),
                CatalogItem.can_sell.is_(True),
            ), 1), else_=0)),
            0,
        ).label("sellable_copies")
        total = func.count(PhysicalCopy.id).label("total_copies")
        stmt = (
            select(CatalogItem, total, rentable, sellable)
            .outerjoin(PhysicalCopy)
            .where(CatalogItem.archived.is_(False))
            .group_by(CatalogItem.id)
        )
        if filters.text.strip():
            term = f"%{filters.text.strip()}%"
            stmt = stmt.where(or_(CatalogItem.title.like(term), CatalogItem.overview.like(term)))
        if filters.item_type:
            stmt = stmt.where(CatalogItem.item_type == ItemType(filters.item_type))
        if filters.genre_id:
            stmt = stmt.where(
                select(ItemGenre.item_id).where(
                    ItemGenre.item_id == CatalogItem.id,
                    ItemGenre.genre_id == filters.genre_id,
                ).exists()
            )
        if filters.year_from:
            stmt = stmt.where(func.year(CatalogItem.release_date) >= filters.year_from)
        if filters.year_to:
            stmt = stmt.where(func.year(CatalogItem.release_date) <= filters.year_to)
        if filters.rating_min is not None:
            stmt = stmt.where(CatalogItem.vote_average >= filters.rating_min)
        if filters.rental_price_min is not None:
            stmt = stmt.where(CatalogItem.rental_price >= filters.rental_price_min)
        if filters.rental_price_max is not None:
            stmt = stmt.where(CatalogItem.rental_price <= filters.rental_price_max)
        if filters.sale_price_min is not None:
            stmt = stmt.where(CatalogItem.sale_price >= filters.sale_price_min)
        if filters.sale_price_max is not None:
            stmt = stmt.where(CatalogItem.sale_price <= filters.sale_price_max)
        if filters.show_id:
            stmt = stmt.where(CatalogItem.show_id == filters.show_id)
        if filters.season_number is not None:
            stmt = stmt.join(Season, CatalogItem.season_id == Season.id).where(Season.season_number == filters.season_number)

        copy_filters = []
        if filters.media_format:
            copy_filters.append(PhysicalCopy.media_format == filters.media_format)
        if filters.condition:
            copy_filters.append(PhysicalCopy.condition == filters.condition)
        if filters.copy_status:
            copy_filters.append(PhysicalCopy.status == filters.copy_status)
        if copy_filters:
            matching_copy = (
                select(PhysicalCopy.id)
                .where(PhysicalCopy.item_id == CatalogItem.id, *copy_filters)
                .correlate(CatalogItem)
                .exists()
            )
            stmt = stmt.where(matching_copy)
        if filters.require_rentable:
            stmt = stmt.having(rentable > 0)
        if filters.require_sellable:
            stmt = stmt.having(sellable > 0)
        if filters.item_rentable:
            stmt = stmt.where(CatalogItem.can_rent.is_(True))
        return stmt, total, rentable, sellable

    def query_catalog(
        self,
        filters: CatalogFilters | None = None,
        page_request: PageRequest = PageRequest(page_size=48),
        sort: SortSpec = SortSpec(),
    ) -> PagedResult[CatalogRow]:
        filters = filters or CatalogFilters()
        stmt, total, rentable, sellable = self._catalog_statement(filters)
        sort_fields = {
            "title": CatalogItem.title,
            "type": CatalogItem.item_type,
            "rating": CatalogItem.vote_average,
            "rental_price": CatalogItem.rental_price,
            "sale_price": CatalogItem.sale_price,
            "total_copies": total,
            "rentable_copies": rentable,
            "sellable_copies": sellable,
            "release_date": CatalogItem.release_date,
        }
        expression = sort_fields.get(sort.field, CatalogItem.title)
        ordering = desc(expression) if sort.descending else expression.asc()
        total_items = int(self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0)
        page_size = max(1, min(page_request.page_size, 200))
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = min(max(1, page_request.page), total_pages)
        rows = self.session.execute(
            stmt.order_by(ordering, CatalogItem.id).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return PagedResult(
            items=tuple(
                CatalogRow(
                    item_id=item.id,
                    item_type=item.item_type,
                    title=item.title,
                    overview=item.overview,
                    release_date=item.release_date,
                    vote_average=item.vote_average,
                    poster_path=item.poster_path,
                    rental_price=Decimal(item.rental_price),
                    sale_price=Decimal(item.sale_price),
                    total_copies=int(copies or 0),
                    rentable_copies=int(rent_count or 0),
                    sellable_copies=int(sell_count or 0),
                )
                for item, copies, rent_count, sell_count in rows
            ),
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )

    def list_catalog(self, text: str = "", item_type: str = "", available_only: bool = False, page: int = 1, page_size: int = 48):
        """Compatibility wrapper for callers that still need ORM catalog rows."""
        filters = CatalogFilters(text=text, item_type=item_type, require_rentable=available_only)
        stmt, total, rentable, sellable = self._catalog_statement(filters)
        return self.session.execute(
            stmt.order_by(CatalogItem.title, CatalogItem.id).offset((max(1, page) - 1) * page_size).limit(page_size)
        ).all()

    def choose_checkout_copy(
        self,
        item_id: int,
        action: LineAction,
        excluded_copy_ids: set[int] | None = None,
    ) -> CopyChoice | None:
        if action not in (LineAction.RENT, LineAction.BUY):
            raise BusinessError("Loại dòng phiếu không hợp lệ.")
        allowed = PhysicalCopy.can_rent.is_(True) if action == LineAction.RENT else PhysicalCopy.can_sell.is_(True)
        item_allowed = CatalogItem.can_rent.is_(True) if action == LineAction.RENT else CatalogItem.can_sell.is_(True)
        stmt = (
            select(PhysicalCopy, CatalogItem)
            .join(CatalogItem)
            .where(
                CatalogItem.id == item_id,
                CatalogItem.archived.is_(False),
                item_allowed,
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                allowed,
            )
            .order_by(PhysicalCopy.barcode)
            .limit(1)
        )
        if excluded_copy_ids:
            stmt = stmt.where(PhysicalCopy.id.not_in(excluded_copy_ids))
        choice = self.session.execute(stmt).one_or_none()
        if not choice:
            return None
        copy, item = choice
        price = copy.rental_price_override or item.rental_price if action == LineAction.RENT else copy.sale_price_override or item.sale_price
        return CopyChoice(copy.id, item.id, copy.barcode, item.title, action, Decimal(price))

    def list_genres(self) -> tuple[Genre, ...]:
        return tuple(self.session.scalars(select(Genre).order_by(Genre.name)))

    def catalog_item(self, item_id: int) -> CatalogItem:
        item = self.session.scalar(
            select(CatalogItem).options(joinedload(CatalogItem.copies), joinedload(CatalogItem.show)).where(CatalogItem.id == item_id)
        )
        if not item:
            raise BusinessError("Không tìm thấy phim/tập phim.")
        return item

    def catalog_metadata(self, item_id: int) -> tuple[tuple[str, ...], tuple[CatalogReview, ...]]:
        item = self.catalog_item(item_id)
        genres = tuple(self.session.scalars(
            select(Genre.name)
            .join(ItemGenre, ItemGenre.genre_id == Genre.id)
            .where(ItemGenre.item_id == item.id)
            .order_by(Genre.name)
        ))
        review_filter = ExternalReview.item_id == item.id
        if item.show_id:
            review_filter = review_filter | (ExternalReview.show_id == item.show_id)
        reviews = tuple(
            CatalogReview(
                review.author or "TMDB",
                Decimal(review.rating) if review.rating is not None else None,
                review.content,
            )
            for review in self.session.scalars(
                select(ExternalReview)
                .where(review_filter)
                .order_by(ExternalReview.published_at.desc(), ExternalReview.id.desc())
                .limit(5)
            )
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
            self.session.add(item)
        self.session.flush()
        self.session.add(AuditLog(
            actor_id=actor_id,
            action="UPDATE_CATALOG" if item_id else "CREATE_CATALOG",
            entity="CatalogItem",
            entity_id=str(item.id),
            detail=item.title,
        ))
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
            for show, season_count in self.session.execute(
                select(Show, func.count(Season.id))
                .outerjoin(Season, Season.show_id == Show.id)
                .where(Show.archived.is_(False))
                .group_by(Show.id)
                .order_by(Show.title)
            ).all()
        ]

    def list_show_episodes(self, show_id: int, season_number: int | None = None) -> list[ShowEpisodeSummary]:
        if not self.session.get(Show, show_id):
            raise BusinessError("Không tìm thấy bộ phim.")
        rentable = func.coalesce(func.sum(case((and_(PhysicalCopy.status == CopyStatus.AVAILABLE, PhysicalCopy.can_rent.is_(True), CatalogItem.can_rent.is_(True)), 1), else_=0)), 0)
        sellable = func.coalesce(func.sum(case((and_(PhysicalCopy.status == CopyStatus.AVAILABLE, PhysicalCopy.can_sell.is_(True), CatalogItem.can_sell.is_(True)), 1), else_=0)), 0)
        stmt = (
            select(CatalogItem, Season.season_number, rentable, sellable)
            .join(Season, CatalogItem.season_id == Season.id)
            .outerjoin(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
            .where(CatalogItem.show_id == show_id, CatalogItem.archived.is_(False))
            .group_by(CatalogItem.id, Season.season_number)
            .order_by(Season.season_number, CatalogItem.episode_number, CatalogItem.id)
        )
        if season_number is not None:
            stmt = stmt.where(Season.season_number == season_number)
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
            for item, number, available, sellable_count in self.session.execute(stmt).all()
        ]

    def create_show(self, title: str, overview: str = "", actor_id: int | None = None) -> Show:
        if actor_id is None:
            raise BusinessError("Cần tài khoản quản lý để thêm bộ phim.")
        self._require_manager(actor_id)
        if not title.strip():
            raise BusinessError("Tên bộ phim là bắt buộc.")
        show = Show(title=title.strip(), overview=overview.strip() or None)
        self.session.add(show)
        self.session.flush()
        self.session.add(AuditLog(actor_id=actor_id, action="CREATE_SHOW", entity="Show", entity_id=str(show.id), detail=show.title))
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
        show = self.session.get(Show, show_id)
        if not show or show.archived:
            raise BusinessError("Không tìm thấy bộ phim.")
        season = self.session.scalar(select(Season).where(Season.show_id == show_id, Season.season_number == season_number))
        if not season:
            season = Season(show_id=show_id, season_number=season_number, name=f"Mùa {season_number}")
            self.session.add(season)
            self.session.flush()
        existing_numbers = set(
            self.session.scalars(
                select(CatalogItem.episode_number).where(CatalogItem.show_id == show_id, CatalogItem.season_id == season.id)
            )
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
            self.session.add(episode)
            episodes.append(episode)
        self.session.flush()
        self.session.add(AuditLog(
            actor_id=actor_id,
            action="BULK_CREATE_EPISODES",
            entity="Show",
            entity_id=str(show.id),
            detail=f"S{season_number} E{first_episode}-{last_episode}",
        ))
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
        if self.session.scalar(select(PhysicalCopy).where(PhysicalCopy.barcode == barcode)):
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
        self.session.add(copy)
        self.session.flush()
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
        saved = {row.media_format: Decimal(row.amount) for row in self.session.scalars(select(DepositDefault))}
        return fallback | saved

    def save_deposit_defaults(self, values: dict[str, Decimal], actor_id: int) -> dict[str, Decimal]:
        self._require_manager(actor_id)
        required = {"VHS", "VCD", "DVD", "Blu-ray"}
        if set(values) != required or any(Decimal(amount) < 0 for amount in values.values()):
            raise BusinessError("Cần nhập mức cọc không âm cho VHS, VCD, DVD và Blu-ray.")
        existing = {row.media_format: row for row in self.session.scalars(select(DepositDefault))}
        before = self.deposit_defaults()
        for media_format, amount in values.items():
            row = existing.get(media_format)
            if row is None:
                self.session.add(DepositDefault(media_format=media_format, amount=Decimal(amount), updated_by=actor_id))
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
        copies = list(self.session.scalars(select(PhysicalCopy).with_for_update()))
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
        copy = self.session.scalar(select(PhysicalCopy).where(PhysicalCopy.id == copy_id).with_for_update())
        if not copy:
            raise BusinessError("Không tìm thấy bản đĩa.")
        if self.session.scalar(select(PhysicalCopy.id).where(PhysicalCopy.barcode == request.barcode.strip(), PhysicalCopy.id != copy_id)):
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
        items = list(self.session.scalars(select(CatalogItem).where(CatalogItem.id.in_(item_ids))))
        for item in items:
            item.archived = True
            self.session.add(AuditLog(actor_id=actor_id, action="ARCHIVE", entity="CatalogItem", entity_id=str(item.id), detail=None))
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
        items = list(self.session.scalars(select(CatalogItem).where(
            CatalogItem.id.in_(set(item_ids)), CatalogItem.archived.is_(False), CatalogItem.can_rent.is_(True)
        )))
        for item in items:
            for key, value in changes.items():
                setattr(item, key, value)
            self.session.add(AuditLog(actor_id=actor_id, action="BULK_PRICE_EDIT", entity="CatalogItem", entity_id=str(item.id), detail=",".join(changes)))
        return len(items)

    def _customer_limit(self, customer: Customer) -> int:
        _factor, adjustment, manager_required = reputation_factor(customer.reputation_score)
        limit = (8 if self.premium_active(customer.id) else 4) + adjustment
        return max(1, limit if not manager_required else 1)

    def _require_manager(self, employee_id: int) -> None:
        role_code = self.session.scalar(
            select(Role.code).join(UserAccount, UserAccount.role_id == Role.id).where(UserAccount.employee_id == employee_id)
        )
        if role_code not in (RoleCode.ADMIN, RoleCode.MANAGER):
            raise BusinessError("Thao tác này cần quyền Quản lý hoặc Quản trị viên.")

    def _open_rental_count(self, customer_id: int) -> int:
        return int(self.session.scalar(
            select(func.count(RentalTerm.id)).join(OrderLine).join(Order).where(
                Order.customer_id == customer_id, RentalTerm.state == RentalState.ACTIVE
            )
        ) or 0)

    def quote(self, customer_id: int, lines: list[CheckoutLine], voucher_code: str | None = None, combo_ids: list[int] | None = None) -> Quote:
        if not lines:
            raise BusinessError("Phiếu chưa có bản đĩa nào.")
        customer = self.session.get(Customer, customer_id)
        if not customer:
            raise BusinessError("Không tìm thấy khách hàng.")
        copies = list(self.session.scalars(select(PhysicalCopy).options(joinedload(PhysicalCopy.item)).where(PhysicalCopy.id.in_([line.copy_id for line in lines]))))
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
        for combo in self.session.scalars(select(Combo).where(Combo.id.in_(combo_ids or []), Combo.active.is_(True))):
            if combo.rule_type == "FIXED":
                required_ids = set(self.session.scalars(select(ComboItem.item_id).where(ComboItem.combo_id == combo.id)))
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
            voucher = self.session.scalar(select(Voucher).where(Voucher.code == voucher_code.strip().upper(), Voucher.active.is_(True)))
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
        locked = list(self.session.scalars(
            select(PhysicalCopy).options(joinedload(PhysicalCopy.item)).where(PhysicalCopy.id.in_([x.copy_id for x in lines])).with_for_update()
        ))
        by_id = {copy.id: copy for copy in locked}
        if any(copy.status != CopyStatus.AVAILABLE for copy in locked):
            raise BusinessError("Tồn kho đã thay đổi, hãy lập lại phiếu.")
        code = order_code or f"PX{datetime.now():%y%m%d%H%M%S}{token_hex(4).upper()}"
        if self.session.scalar(select(Order.id).where(Order.code == code)):
            raise BusinessError("Mã phiếu đã tồn tại.")
        order = Order(code=code, customer_id=customer_id, employee_id=employee_id, shift_id=shift_id,
                      gross_total=quote.gross, discount_total=quote.discount, deposit_total=quote.deposit)
        self.session.add(order)
        self.session.flush()
        for source, amount in quote.discount_sources.items():
            self.session.add(OrderDiscount(
                order_id=order.id,
                source=source,
                amount=amount,
                source_code=quote.discount_source_codes.get(source),
            ))
        customer = self.session.get(Customer, customer_id)
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
            self.session.add(line)
            self.session.flush()
            before = copy.status
            if request.action == LineAction.RENT:
                copy.status = CopyStatus.RENTED
                term = RentalTerm(line_id=line.id, due_date=request.due_date, issued_condition=copy.condition)
                self.session.add(term)
                self.session.flush()
                for event, scheduled_for in scheduled_reminders(request.due_date):
                    for channel in ("EMAIL", "SMS"):
                        self.session.add(
                            NotificationOutbox(
                                customer_id=customer_id,
                                rental_term_id=term.id,
                                channel=channel,
                                event=event,
                                scheduled_for=scheduled_for,
                                dedupe_key=f"rental:{term.id}:{channel.lower()}:{event}",
                            )
                        )
            else:
                copy.status = CopyStatus.SOLD
            self._status_history(copy, before, copy.status, f"Phiếu {code}", employee_id)
        paid = sum((Decimal(p.amount) for p in payments), Decimal("0"))
        for payment in payments:
            self.session.add(PaymentTransaction(order_id=order.id, customer_id=customer_id, employee_id=employee_id,
                             method=payment.method, category="CHECKOUT", amount=Decimal(payment.amount)))
        if paid < quote.total_due:
            order.status = "PARTIALLY_PAID"
        self._audit(employee_id, "CHECKOUT", "Order", order.id, {
            "code": order.code, "customer_id": customer_id, "line_count": len(lines),
            "discount": str(quote.discount), "deposit": str(quote.deposit),
        })
        return order

    def query_active_rentals(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("due", False)) -> PagedResult[ActiveRental]:
        stmt = (
            select(RentalTerm, OrderLine, Order, Customer, PhysicalCopy)
            .join(OrderLine, RentalTerm.line_id == OrderLine.id)
            .join(Order, OrderLine.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .join(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .where(RentalTerm.state == RentalState.ACTIVE)
        )
        fields = {"title": OrderLine.title_snapshot, "customer": Customer.full_name, "due": RentalTerm.due_date, "status": RentalTerm.due_date}
        expression = fields.get(sort.field, RentalTerm.due_date)
        page = self._page_rows(stmt.order_by(desc(expression) if sort.descending else expression.asc(), RentalTerm.id), page_request)
        return PagedResult(tuple(
            ActiveRental(term.id, customer.id, customer.full_name, line.title_snapshot, copy.barcode, term.due_date)
            for term, line, _order, customer, copy in page.items
        ), page.page, page.page_size, page.total_items, page.total_pages)

    def active_rentals(self) -> list[ActiveRental]:
        return list(self.query_active_rentals(PageRequest(1, 10_000)).items)

    def query_orders(self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created_at", True)) -> PagedResult[OrderSummary]:
        stmt = (
            select(Order, Customer, Employee)
            .join(Customer, Order.customer_id == Customer.id)
            .join(Employee, Order.employee_id == Employee.id)
        )
        if text.strip():
            term = f"%{text.strip()}%"
            stmt = stmt.where((Order.code.like(term)) | (Customer.full_name.like(term)))
        total_due = Order.gross_total - Order.discount_total + Order.deposit_total
        fields = {"title": Order.code, "customer": Customer.full_name, "employee": Employee.full_name, "created": Order.created_at, "created_at": Order.created_at, "status": Order.status, "total": total_due}
        expression = fields.get(sort.field, Order.created_at)
        stmt = stmt.order_by(desc(expression) if sort.descending else expression.asc(), Order.id)
        page = self._page_rows(stmt, page_request)
        return PagedResult(tuple(
            OrderSummary(order.id, order.code, customer.full_name, employee.full_name, order.created_at, order.status, Decimal(order.gross_total) - Decimal(order.discount_total) + Decimal(order.deposit_total))
            for order, customer, employee in page.items
        ), page.page, page.page_size, page.total_items, page.total_pages)

    def list_orders(self, text: str = "", limit: int = 200) -> list[OrderSummary]:
        return list(self.query_orders(text, PageRequest(1, limit)).items)

    def order_detail(self, order_id: int) -> tuple[OrderSummary, list[OrderDetailLine]]:
        order, customer, employee = self.session.execute(
            select(Order, Customer, Employee)
            .join(Customer, Order.customer_id == Customer.id)
            .join(Employee, Order.employee_id == Employee.id)
            .where(Order.id == order_id)
        ).one_or_none() or (None, None, None)
        if not order:
            raise BusinessError("Không tìm thấy phiếu.")
        lines = self.session.execute(
            select(OrderLine, PhysicalCopy, RentalTerm)
            .outerjoin(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .outerjoin(RentalTerm, RentalTerm.line_id == OrderLine.id)
            .where(OrderLine.order_id == order_id)
            .order_by(OrderLine.id)
        ).all()
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
        row = self.session.execute(
            select(Order, Customer, Employee)
            .join(Customer, Order.customer_id == Customer.id)
            .join(Employee, Order.employee_id == Employee.id)
            .where(Order.id == order_id)
        ).one_or_none()
        if not row:
            raise BusinessError("Không tìm thấy phiếu.")
        order, customer, employee = row
        line_rows = self.session.execute(
            select(OrderLine, PhysicalCopy, RentalTerm)
            .outerjoin(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .outerjoin(RentalTerm, RentalTerm.line_id == OrderLine.id)
            .where(OrderLine.order_id == order_id)
            .order_by(OrderLine.id)
        ).all()
        discounts = tuple(
            ReceiptDiscount(discount.source, Decimal(discount.amount), discount.source_code)
            for discount in self.session.scalars(
                select(OrderDiscount).where(OrderDiscount.order_id == order_id).order_by(OrderDiscount.id)
            )
        )
        payments = tuple(
            ReceiptPayment(payment.method, payment.category, Decimal(payment.amount), payment.created_at)
            for payment in self.session.scalars(
                select(PaymentTransaction)
                .where(PaymentTransaction.order_id == order_id)
                .order_by(PaymentTransaction.created_at, PaymentTransaction.id)
            )
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
        if not self.session.get(Order, order_id):
            raise BusinessError("Không tìm thấy phiếu.")
        self._audit(actor_id, "EXPORT_ORDER_PDF", "Order", order_id, {
            "layout": layout,
            "filename": filename,
        })

    def return_rentals(self, employee_id: int, customer_id: int, returns: list[tuple[int, ReturnOutcome, str]], payment: PaymentInput | None = None, today: date | None = None) -> Decimal:
        today = today or date.today()
        receipt = ReturnReceipt(customer_id=customer_id, employee_id=employee_id, returned_on=today)
        self.session.add(receipt)
        self.session.flush()
        balance = Decimal("0")
        returned_item_ids: set[int] = set()
        for term_id, outcome, note in returns:
            term = self.session.scalar(
                select(RentalTerm)
                .options(
                    joinedload(RentalTerm.line).joinedload(OrderLine.order),
                    joinedload(RentalTerm.line).joinedload(OrderLine.copy).joinedload(PhysicalCopy.item),
                )
                .where(RentalTerm.id == term_id)
                .with_for_update()
            )
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
                self.session.add(PenaltyCharge(rental_term_id=term.id, kind="LATE", amount=late, reason="Trả quá hạn"))
            if damage:
                self.session.add(PenaltyCharge(rental_term_id=term.id, kind=outcome.value, amount=damage, reason=note or outcome.value))
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
            self.session.add(ReturnLine(receipt_id=receipt.id, rental_term_id=term.id, outcome=outcome.value, note=note or None))
            self._status_history(copy, before, copy.status, f"Trả đĩa: {outcome.value}", employee_id)
        for item_id in returned_item_ids:
            self.allocate_waiting_reservations(item_id)
        if balance < 0:
            self.session.add(PaymentTransaction(customer_id=customer_id, employee_id=employee_id, method=PaymentMethod.CASH, category="DEPOSIT_REFUND", amount=balance))
        elif payment:
            amount = Decimal(payment.amount)
            if amount < 0 or amount > balance:
                raise BusinessError("Khoản thu thêm không hợp lệ.")
            if amount:
                self.session.add(PaymentTransaction(customer_id=customer_id, employee_id=employee_id, method=payment.method, category="RETURN_SETTLEMENT", amount=amount))
        self._audit(employee_id, "RETURN_RENTAL", "ReturnReceipt", receipt.id, {
            "customer_id": customer_id, "lines": len(returns), "balance": str(balance),
        })
        return balance

    def extend_rental(self, rental_term_id: int, employee_id: int, days: int = 3) -> RentalTerm:
        term = self.session.scalar(
            select(RentalTerm)
            .options(joinedload(RentalTerm.line).joinedload(OrderLine.copy))
            .where(RentalTerm.id == rental_term_id)
            .with_for_update()
        )
        if not term or term.state != RentalState.ACTIVE:
            raise BusinessError("Chỉ có thể gia hạn dòng thuê đang hoạt động.")
        if days != 3:
            raise BusinessError("Mỗi lần gia hạn chuẩn là 3 ngày.")
        has_waiting_reservation = self.session.scalar(
            select(Reservation.id).where(
                Reservation.item_id == term.line.copy.item_id,
                Reservation.state == ReservationState.WAITING,
            )
        ) is not None
        if term.due_date < date.today() or has_waiting_reservation:
            self._require_manager(employee_id)
        old_due_date = term.due_date
        term.due_date += timedelta(days=days)
        copy = term.line.copy
        assert copy is not None
        self.session.add(
            PaymentTransaction(
                order_id=term.line.order_id,
                customer_id=self.session.get(Order, term.line.order_id).customer_id,
                employee_id=employee_id,
                method=PaymentMethod.CASH,
                category="RENTAL_EXTENSION",
                amount=copy.rental_price_override or copy.item.rental_price,
            )
        )
        self.session.add(
            RentalExtension(
                rental_term_id=term.id,
                old_due_date=old_due_date,
                new_due_date=term.due_date,
                fee=copy.rental_price_override or copy.item.rental_price,
                employee_id=employee_id,
            )
        )
        self._audit(employee_id, "EXTEND_RENTAL", "RentalTerm", term.id, {"days": days, "due_date": str(term.due_date)})
        return term

    def rental_to_sale(self, rental_term_id: int, employee_id: int, payment: PaymentInput) -> Order:
        if Decimal(payment.amount) < 0:
            raise BusinessError("Khoản thanh toán không được âm.")
        term = self.session.scalar(
            select(RentalTerm)
            .options(joinedload(RentalTerm.line).joinedload(OrderLine.copy).joinedload(PhysicalCopy.item))
            .where(RentalTerm.id == rental_term_id)
            .with_for_update()
        )
        if not term or term.state != RentalState.ACTIVE:
            raise BusinessError("Dòng thuê không thể chuyển thành mua.")
        source = term.line
        copy = source.copy
        assert copy is not None
        if not copy.can_sell or not copy.item.can_sell:
            raise BusinessError("Bản đĩa đang thuê không cho phép bán.")
        order = self.session.get(Order, source.order_id)
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
        self.session.add(sale)
        self.session.flush()
        self.session.add(
            OrderLine(
                order_id=sale.id,
                copy_id=copy.id,
                action=LineAction.BUY,
                title_snapshot=copy.item.title,
                unit_price=sale_price,
                discount_amount=applied_deposit,
                source_rental_line_id=source.id,
            )
        )
        term.state = RentalState.PURCHASED
        before = copy.status
        copy.status = CopyStatus.SOLD
        self._status_history(copy, before, copy.status, f"Chuyển thuê thành mua: {sale.code}", employee_id)
        self.session.add(
            PaymentTransaction(
                order_id=sale.id,
                customer_id=order.customer_id,
                employee_id=employee_id,
                method=payment.method,
                category="RENTAL_TO_SALE",
                amount=payment.amount,
            )
        )
        self._audit(employee_id, "RENTAL_TO_SALE", "Order", sale.id, {"source_line_id": source.id, "deposit_applied": str(applied_deposit)})
        return sale

    def returnable_sales(self, today: date | None = None) -> list[ReturnableSale]:
        today = today or date.today()
        rows = self.session.execute(
            select(OrderLine, Order, Customer, PhysicalCopy)
            .join(Order, OrderLine.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .join(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .where(
                OrderLine.action == LineAction.BUY,
                PhysicalCopy.status == CopyStatus.SOLD,
                Order.created_at >= datetime.combine(today - timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc),
            )
            .order_by(Order.created_at.desc())
        ).all()
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
        line = self.session.scalar(
            select(OrderLine)
            .options(joinedload(OrderLine.copy), joinedload(OrderLine.order))
            .where(OrderLine.id == sale_line_id, OrderLine.action == LineAction.BUY)
            .with_for_update()
        )
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
        self.session.add(
            PaymentTransaction(
                order_id=line.order_id,
                customer_id=line.order.customer_id,
                employee_id=employee_id,
                method=PaymentMethod.CASH,
                category="SALE_REFUND",
                amount=-refund,
            )
        )
        self.session.add(
            SaleReturn(
                sale_line_id=line.id,
                employee_id=employee_id,
                returned_on=today,
                refund_amount=refund,
                note=status_note,
            )
        )
        self._audit(employee_id, "RETURN_SALE", "SaleReturn", line.id, {"refund": str(refund), "condition": condition.value})
        return refund

    def query_inventory(self, status: CopyStatus | None = None, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("title")) -> PagedResult[InventoryCopy]:
        stmt = select(PhysicalCopy, CatalogItem).join(CatalogItem)
        if status:
            stmt = stmt.where(PhysicalCopy.status == status)
        fields = {"title": CatalogItem.title, "barcode": PhysicalCopy.barcode, "format": PhysicalCopy.media_format, "condition": PhysicalCopy.condition, "status": PhysicalCopy.status, "rent": PhysicalCopy.can_rent, "sell": PhysicalCopy.can_sell, "buy": PhysicalCopy.can_sell}
        expression = fields.get(sort.field, CatalogItem.title)
        stmt = stmt.order_by(desc(expression) if sort.descending else expression.asc(), PhysicalCopy.id)
        page = self._page_rows(stmt, page_request)
        return PagedResult(tuple(
            InventoryCopy(copy.id, copy.barcode, item.title, copy.media_format, copy.condition, copy.status, copy.can_rent, copy.can_sell)
            for copy, item in page.items
        ), page.page, page.page_size, page.total_items, page.total_pages)

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
        copy = self.session.scalar(select(PhysicalCopy).where(PhysicalCopy.id == copy_id).with_for_update())
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
        if not self.session.get(Customer, customer_id):
            raise BusinessError("Không tìm thấy khách hàng.")
        items = list(self.session.scalars(select(CatalogItem).where(CatalogItem.id.in_(set(item_ids)), CatalogItem.archived.is_(False))))
        if len(items) != len(set(item_ids)):
            raise BusinessError("Có phim hoặc tập phim không tồn tại.")
        reservations = []
        for item_id in set(item_ids):
            duplicate = self.session.scalar(
                select(Reservation.id).where(
                    Reservation.customer_id == customer_id,
                    Reservation.item_id == item_id,
                    Reservation.state.in_([ReservationState.WAITING, ReservationState.HELD]),
                )
            )
            if duplicate:
                raise BusinessError("Khách hàng đã có đặt trước đang hiệu lực cho item này.")
            reservation = Reservation(customer_id=customer_id, item_id=item_id)
            self.session.add(reservation)
            reservations.append(reservation)
        self.session.flush()
        for item_id in {reservation.item_id for reservation in reservations}:
            self.allocate_waiting_reservations(item_id)
        self._audit(actor_id, "CREATE_RESERVATION", "Reservation", ",".join(str(row.id) for row in reservations), {
            "customer_id": customer_id, "item_ids": sorted({row.item_id for row in reservations}),
        })
        return reservations

    def query_reservations(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created", True)) -> PagedResult[ReservationView]:
        stmt = (
            select(Reservation, Customer, CatalogItem)
            .join(Customer, Reservation.customer_id == Customer.id)
            .join(CatalogItem, Reservation.item_id == CatalogItem.id)
        )
        fields = {"customer": Customer.full_name, "item": CatalogItem.title, "state": Reservation.state, "hold": Reservation.hold_until, "created": Reservation.created_at}
        expression = fields.get(sort.field, Reservation.created_at)
        page = self._page_rows(stmt.order_by(desc(expression) if sort.descending else expression.asc(), Reservation.id), page_request)
        return PagedResult(tuple(
            ReservationView(reservation.id, customer.full_name, item.title, reservation.state, reservation.hold_until)
            for reservation, customer, item in page.items
        ), page.page, page.page_size, page.total_items, page.total_pages)

    def list_reservations(self) -> list[ReservationView]:
        return list(self.query_reservations(PageRequest(1, 10_000)).items)

    def expire_reservation_holds(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        reservations = list(
            self.session.scalars(
                select(Reservation)
                .where(Reservation.state == ReservationState.HELD, Reservation.hold_until <= now)
                .with_for_update()
            )
        )
        item_ids: set[int] = set()
        for reservation in reservations:
            copy = self.session.scalar(
                select(PhysicalCopy).where(PhysicalCopy.id == reservation.allocated_copy_id).with_for_update()
            )
            if copy and copy.status == CopyStatus.HELD:
                copy.status = CopyStatus.AVAILABLE
                self._status_history(copy, CopyStatus.HELD, CopyStatus.AVAILABLE, "Hết hạn giữ chỗ")
            reservation.state = ReservationState.EXPIRED
            item_ids.add(reservation.item_id)
        for item_id in item_ids:
            self.allocate_waiting_reservations(item_id)
        return len(reservations)

    def allocate_waiting_reservations(self, item_id: int) -> int:
        copies = list(self.session.scalars(select(PhysicalCopy).where(PhysicalCopy.item_id == item_id, PhysicalCopy.status == CopyStatus.AVAILABLE).order_by(PhysicalCopy.id).with_for_update()))
        reservations = list(self.session.scalars(select(Reservation).where(Reservation.item_id == item_id, Reservation.state == ReservationState.WAITING).order_by(Reservation.created_at).with_for_update()))
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
        rented = self.session.scalar(select(func.count(PhysicalCopy.id)).where(PhysicalCopy.status == CopyStatus.RENTED)) or 0
        available = self.session.scalar(select(func.count(PhysicalCopy.id)).where(PhysicalCopy.status == CopyStatus.AVAILABLE)) or 0
        overdue = self.session.scalar(select(func.count(RentalTerm.id)).where(RentalTerm.state == RentalState.ACTIVE, RentalTerm.due_date < today)) or 0
        held = self.session.scalar(select(func.count(Reservation.id)).where(Reservation.state.in_([ReservationState.WAITING, ReservationState.HELD]))) or 0
        cash_flow = self.session.scalar(select(func.coalesce(func.sum(PaymentTransaction.amount), 0))) or Decimal("0")
        return {"available": available, "rented": rented, "overdue": overdue, "reservations": held, "cash_flow": Decimal(cash_flow)}

    def today_recommendations(self, limit: int = 8) -> list[Recommendation]:
        return today_recommendations(
            self.session, limit, self.gemini_api_key, self.gemini_generation_model
        )

    def customer_recommendations(self, customer_id: int, limit: int = 8) -> list[Recommendation]:
        if not self.session.get(Customer, customer_id):
            raise BusinessError("Không tìm thấy khách hàng.")
        return for_customer(
            self.session, customer_id, limit, self.gemini_api_key, self.gemini_generation_model
        )

    def query_notifications(self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("scheduled", True)) -> PagedResult[NotificationSummary]:
        rows = select(NotificationOutbox, Customer).join(Customer, NotificationOutbox.customer_id == Customer.id)
        fields = {"customer": Customer.full_name, "channel": NotificationOutbox.channel, "event": NotificationOutbox.event, "scheduled": NotificationOutbox.scheduled_for, "status": NotificationOutbox.status, "attempts": NotificationOutbox.attempts}
        expression = fields.get(sort.field, NotificationOutbox.scheduled_for)
        page = self._page_rows(rows.order_by(desc(expression) if sort.descending else expression.asc(), NotificationOutbox.id), page_request)
        return PagedResult(tuple(
            NotificationSummary(outbox.id, customer.full_name, outbox.channel, outbox.event, outbox.scheduled_for, str(outbox.status), outbox.attempts, outbox.error)
            for outbox, customer in page.items
        ), page.page, page.page_size, page.total_items, page.total_pages)

    def list_notifications(self, limit: int = 300) -> list[NotificationSummary]:
        return list(self.query_notifications(PageRequest(1, limit)).items)

    def query_audit_logs(
        self,
        filters: AuditQuery = AuditQuery(),
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("created", True),
    ) -> PagedResult[AuditView]:
        stmt = select(AuditLog, Employee).outerjoin(Employee, AuditLog.actor_id == Employee.id)
        if filters.action.strip():
            stmt = stmt.where(AuditLog.action == filters.action.strip())
        if filters.actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == filters.actor_id)
        if filters.text.strip():
            pattern = f"%{filters.text.strip()}%"
            stmt = stmt.where(
                (AuditLog.action.like(pattern)) | (AuditLog.entity.like(pattern)) |
                (AuditLog.entity_id.like(pattern))
            )
        fields = {
            "created": AuditLog.created_at, "actor": Employee.full_name, "action": AuditLog.action,
            "entity": AuditLog.entity, "entity_id": AuditLog.entity_id,
        }
        expression = fields.get(sort.field, AuditLog.created_at)
        page = self._page_rows(
            stmt.order_by(desc(expression) if sort.descending else expression.asc(), AuditLog.id), page_request
        )
        return PagedResult(tuple(
            AuditView(
                log.id, log.created_at, employee.full_name if employee else None,
                log.action, log.entity, log.entity_id, log.detail,
            )
            for log, employee in page.items
        ), page.page, page.page_size, page.total_items, page.total_pages)

    def ensure_mock_fixtures(self, actor_id: int) -> MockFixtureResult:
        """Create stable fixtures in a transaction separate from daily mock orders."""
        self._require_manager(actor_id)
        today = date.today()
        combo_count = voucher_count = membership_count = 0
        item_ids = list(self.session.scalars(
            select(CatalogItem.id).join(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id).where(
                CatalogItem.archived.is_(False), CatalogItem.can_rent.is_(True),
                PhysicalCopy.status == CopyStatus.AVAILABLE, PhysicalCopy.can_rent.is_(True),
            ).distinct().order_by(CatalogItem.id).limit(20)
        ))
        show_ids = list(self.session.scalars(
            select(CatalogItem.show_id).join(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id).where(
                CatalogItem.item_type == ItemType.EPISODE, CatalogItem.show_id.is_not(None),
                CatalogItem.archived.is_(False), CatalogItem.can_rent.is_(True),
                PhysicalCopy.status == CopyStatus.AVAILABLE, PhysicalCopy.can_rent.is_(True),
            ).group_by(CatalogItem.show_id).having(func.count(func.distinct(CatalogItem.id)) >= 2).order_by(CatalogItem.show_id).limit(10)
        ))
        if len(item_ids) < 20 or len(show_ids) < 10:
            raise BusinessError("Kho chưa đủ phim/tập còn thuê để tạo 20 combo mock.")
        for index in range(10):
            name = f"MOCK-COMBO-FIXED-{index + 1:02d}"
            if self.session.scalar(select(Combo.id).where(Combo.name == name)):
                continue
            combo = Combo(name=name, rule_type="FIXED", discount_amount=Decimal("10000"), active=True)
            self.session.add(combo)
            self.session.flush()
            self.session.add_all([
                ComboItem(combo_id=combo.id, item_id=item_ids[index * 2]),
                ComboItem(combo_id=combo.id, item_id=item_ids[index * 2 + 1]),
            ])
            combo_count += 1
        for index, show_id in enumerate(show_ids, start=1):
            name = f"MOCK-COMBO-SHOW-{index:02d}"
            if self.session.scalar(select(Combo.id).where(Combo.name == name)):
                continue
            self.session.add(Combo(name=name, rule_type="EPISODE_SHOW", show_id=show_id, required_count=2, discount_amount=Decimal("12000"), active=True))
            combo_count += 1
        for index in range(1, 51):
            code = f"MOCKV{index:02d}"
            if self.session.scalar(select(Voucher.id).where(Voucher.code == code)):
                continue
            starts, ends = ((today - timedelta(days=60), None) if index <= 20 else
                            ((today - timedelta(days=180), today - timedelta(days=1)) if index <= 35 else
                             (today + timedelta(days=30), today + timedelta(days=90))))
            self.session.add(Voucher(code=code, percent_off=Decimal("10") if index % 2 else None,
                amount_off=Decimal("15000") if index % 2 == 0 else None, starts_on=starts, ends_on=ends))
            voucher_count += 1
        customers = list(self.session.scalars(select(Customer).order_by(Customer.id)))
        occupied = set(self.session.scalars(select(PremiumMembership.customer_id)))
        active = set(self.session.scalars(select(PremiumMembership.customer_id).where(PremiumMembership.starts_on <= today, PremiumMembership.ends_on >= today)))
        expired = set(self.session.scalars(select(PremiumMembership.customer_id).where(PremiumMembership.ends_on < today)))
        for customer in customers:
            if len(active) >= 300:
                break
            if customer.id in occupied:
                continue
            starts = today - timedelta(days=30 + customer.id % 20)
            self.session.add(PremiumMembership(customer_id=customer.id, starts_on=starts, ends_on=starts + timedelta(days=364), price_paid=Decimal("499000")))
            occupied.add(customer.id); active.add(customer.id); membership_count += 1
        for customer in customers:
            if len(expired) >= 150:
                break
            if customer.id in occupied:
                continue
            starts = today - timedelta(days=500 + customer.id % 40)
            self.session.add(PremiumMembership(customer_id=customer.id, starts_on=starts, ends_on=starts + timedelta(days=89), price_paid=Decimal("159000")))
            occupied.add(customer.id); expired.add(customer.id); membership_count += 1
        self._audit(actor_id, "CREATE_MOCK_FIXTURES", "MockFixtures", "20260908", {"combos": combo_count, "vouchers": voucher_count, "memberships": membership_count})
        return MockFixtureResult(combo_count, voucher_count, membership_count)

    def seed_mock_day(self, business_date: date, actor_id: int, volume_per_day: int = 250) -> int:
        self._require_manager(actor_id)
        today = date.today()
        if business_date > today or not 1 <= volume_per_day <= 250:
            raise BusinessError("Mock chỉ hỗ trợ ngày đến hôm nay và tối đa 250 phiếu/ngày.")
        if self.session.scalar(select(MockDailyRun.id).where(MockDailyRun.business_date == business_date)):
            return 0
        customers = list(self.session.scalars(select(Customer).order_by(Customer.id)))
        available = list(self.session.scalars(
            select(PhysicalCopy).join(PhysicalCopy.item).options(joinedload(PhysicalCopy.item)).where(
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                or_(and_(PhysicalCopy.can_rent.is_(True), CatalogItem.can_rent.is_(True)), and_(PhysicalCopy.can_sell.is_(True), CatalogItem.can_sell.is_(True))),
            ).order_by(PhysicalCopy.id).limit(volume_per_day * 4)
        ))
        if not customers or len(available) < volume_per_day * 2:
            raise BusinessError("Kho hoặc khách hàng không đủ để tạo dữ liệu mock.")
        combos = list(self.session.scalars(select(Combo).where(Combo.name.like("MOCK-COMBO-%"), Combo.active.is_(True))))
        active_vouchers = list(self.session.scalars(
            select(Voucher.code).where(
                Voucher.code.like("MOCKV%"), Voucher.active.is_(True),
                # checkout validates voucher eligibility using the current business date.
                # Historical mock orders must therefore draw only vouchers it can accept now.
                or_(Voucher.starts_on.is_(None), Voucher.starts_on <= today),
                or_(Voucher.ends_on.is_(None), Voucher.ends_on >= today),
            ).order_by(Voucher.code)
        ))
        premium_ids = set(self.session.scalars(select(PremiumMembership.customer_id).where(PremiumMembership.starts_on <= business_date, PremiumMembership.ends_on >= business_date)))
        open_counts = dict(self.session.execute(select(Order.customer_id, func.count(RentalTerm.id)).join(OrderLine, OrderLine.order_id == Order.id).join(RentalTerm, RentalTerm.line_id == OrderLine.id).where(RentalTerm.state == RentalState.ACTIVE).group_by(Order.customer_id)).all())
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
                    for item_id in self.session.scalars(select(ComboItem.item_id).where(ComboItem.combo_id == combo.id)):
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
            for payment in self.session.scalars(select(PaymentTransaction).where(PaymentTransaction.order_id == order.id)):
                payment.created_at = payment.updated_at = timestamp
            if business_date < today:
                terms = list(self.session.scalars(select(RentalTerm).join(OrderLine).where(OrderLine.order_id == order.id)))
                if terms:
                    receipt = ReturnReceipt(customer_id=customer.id, employee_id=actor_id, returned_on=business_date + timedelta(days=3))
                    self.session.add(receipt)
                    self.session.flush()
                    refund = Decimal("0")
                    for term in terms:
                        term.state, term.returned_on = RentalState.RETURNED, term.due_date
                        copy = self.session.get(PhysicalCopy, term.line.copy_id)
                        if copy:
                            copy.status = CopyStatus.AVAILABLE
                        self.session.add(ReturnLine(receipt_id=receipt.id, rental_term_id=term.id, outcome="NORMAL"))
                        refund += Decimal(term.line.deposit_amount)
                    if refund:
                        self.session.add(PaymentTransaction(
                            order_id=order.id, customer_id=customer.id, employee_id=actor_id,
                            method=PaymentMethod.CASH, category="DEPOSIT_REFUND", amount=-refund,
                            note="Mock historical return", created_at=timestamp, updated_at=timestamp,
                        ))
            else:
                open_counts[customer.id] = open_counts.get(customer.id, 0) + rent_count
        self.session.add(MockDailyRun(business_date=business_date, seed_version="20260908", actor_id=actor_id, stats={"orders": volume_per_day, "volume": volume_per_day}))
        self._audit(actor_id, "GENERATE_MOCK_DAY", "MockDailyRun", business_date.isoformat(), {"orders": volume_per_day})
        return volume_per_day

    def _ensure_mock_fixtures(self, actor_id: int) -> None:
        """Create stable promotion/Premium fixtures once without duplicating rows."""
        customers = list(self.session.scalars(select(Customer).order_by(Customer.id).limit(450)))
        existing_members = set(self.session.scalars(select(PremiumMembership.customer_id)))
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
            self.session.add(membership)
        for index in range(1, 51):
            code = f"MOCKV{index:02d}"
            if self.session.scalar(select(Voucher.id).where(Voucher.code == code)):
                continue
            starts = date.today() - timedelta(days=60) if index <= 20 else (
                date.today() - timedelta(days=180) if index <= 35 else date.today() + timedelta(days=30)
            )
            ends = None if index <= 20 else (date.today() - timedelta(days=1) if index <= 35 else date.today() + timedelta(days=90))
            self.session.add(Voucher(
                code=code, percent_off=Decimal("10") if index % 2 else None,
                amount_off=Decimal("15000") if index % 2 == 0 else None,
                starts_on=starts, ends_on=ends,
            ))
        item_ids = list(self.session.scalars(select(CatalogItem.id).where(CatalogItem.archived.is_(False)).order_by(CatalogItem.id).limit(40)))
        existing = int(self.session.scalar(select(func.count(Combo.id))) or 0)
        for index in range(existing, min(20, len(item_ids) // 2)):
            combo = Combo(name=f"Combo mock {index + 1:02d}", rule_type="FIXED", discount_amount=Decimal("10000"), active=True)
            self.session.add(combo); self.session.flush()
            self.session.add_all([ComboItem(combo_id=combo.id, item_id=item_ids[index * 2]), ComboItem(combo_id=combo.id, item_id=item_ids[index * 2 + 1])])

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
        customers = list(self.session.scalars(select(Customer).order_by(Customer.id)))
        if not customers:
            raise BusinessError("Cần có khách hàng trước khi tạo dữ liệu mock.")
        created_days = skipped_days = orders_created = 0
        cursor = start_on
        while cursor <= end_on:
            if self.session.scalar(select(MockDailyRun.id).where(MockDailyRun.business_date == cursor)):
                skipped_days += 1; cursor += timedelta(days=1); continue
            rng = Random(cursor.toordinal())
            available = list(self.session.scalars(
                select(PhysicalCopy).options(joinedload(PhysicalCopy.item)).where(
                    PhysicalCopy.status == CopyStatus.AVAILABLE
                ).order_by(PhysicalCopy.id).limit(volume_per_day * 4)
            ))
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
                for payment in self.session.scalars(select(PaymentTransaction).where(PaymentTransaction.order_id == order.id)):
                    payment.created_at = payment.updated_at = timestamp
                if cursor < date.today():
                    terms = list(self.session.scalars(
                        select(RentalTerm).join(OrderLine).where(OrderLine.order_id == order.id)
                    ))
                    if terms:
                        receipt = ReturnReceipt(customer_id=customer.id, employee_id=actor_id, returned_on=cursor + timedelta(days=3))
                        self.session.add(receipt); self.session.flush()
                        refund = Decimal("0")
                        for term in terms:
                            term.state, term.returned_on = RentalState.RETURNED, term.due_date
                            copy = self.session.get(PhysicalCopy, term.line.copy_id)
                            if copy:
                                copy.status = CopyStatus.AVAILABLE
                            self.session.add(ReturnLine(receipt_id=receipt.id, rental_term_id=term.id, outcome="NORMAL"))
                            refund += Decimal(term.line.deposit_amount)
                        if refund:
                            self.session.add(PaymentTransaction(
                                order_id=order.id, customer_id=customer.id, employee_id=actor_id,
                                method=PaymentMethod.CASH, category="DEPOSIT_REFUND", amount=-refund,
                                note="Mock historical return", created_at=timestamp, updated_at=timestamp,
                            ))
                created_for_day += 1
            self.session.add(MockDailyRun(
                business_date=cursor, seed_version="20260907", actor_id=actor_id,
                stats={"orders": created_for_day, "volume": volume_per_day},
            ))
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
            if self.session.scalar(select(MockDailyRun.id).where(MockDailyRun.business_date == cursor)):
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
            self.session,
            description,
            self.gemini_api_key,
            self.gemini_embedding_model,
            self.gemini_embedding_dimensions,
        )

    def search_by_description(self, description: str) -> list[SearchResult]:
        """Compatibility API for callers that only need the result rows."""
        return list(self.search_by_description_response(description).items)

    def operational_report(
        self,
        start_on: date | None = None,
        end_on: date | None = None,
    ) -> OperationalReport:
        return operational_report(self.session, start_on=start_on, end_on=end_on)

    def _status_history(self, copy: PhysicalCopy, before: CopyStatus | None, after: CopyStatus, note: str, actor_id: int | None = None) -> None:
        self.session.add(CopyStatusHistory(copy_id=copy.id, from_status=before, to_status=after, note=note, actor_id=actor_id))


def run_mock_seed(
    factory: sessionmaker[Session],
    request: MockSeedRequest,
    progress: Callable[[int, int], None] | None = None,
) -> MockSeedResult:
    """Run fixtures once and commit each business day independently."""
    if request.end_on < request.start_on or (request.end_on - request.start_on).days > 30:
        raise BusinessError("Khoảng mock tối đa 31 ngày.")
    with factory() as session:
        service = StoreService(session)
        try:
            fixtures = service.ensure_mock_fixtures(request.actor_id)
            session.commit()
        except Exception:
            session.rollback()
            raise
    created_days = skipped_days = orders_created = 0
    total_days = (request.end_on - request.start_on).days + 1
    cursor = request.start_on
    while cursor <= request.end_on:
        with factory() as session:
            service = StoreService(session)
            try:
                if session.scalar(select(MockDailyRun.id).where(MockDailyRun.business_date == cursor)):
                    skipped_days += 1
                else:
                    orders_created += service.seed_mock_day(cursor, request.actor_id, request.volume_per_day)
                    session.commit()
                    created_days += 1
            except Exception as exc:
                session.rollback()
                return MockSeedResult(
                    created_days, skipped_days, orders_created, failed_on=cursor, error=str(exc),
                    combos_created=fixtures.combos_created, vouchers_created=fixtures.vouchers_created,
                    memberships_created=fixtures.memberships_created,
                )
        if progress:
            progress((cursor - request.start_on).days + 1, total_days)
        cursor += timedelta(days=1)
    return MockSeedResult(
        created_days, skipped_days, orders_created,
        combos_created=fixtures.combos_created, vouchers_created=fixtures.vouchers_created,
        memberships_created=fixtures.memberships_created,
    )
