from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    relationship,
    sessionmaker,
)

from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    ItemType,
    LineAction,
    NotificationStatus,
    PaymentMethod,
    RentalState,
    ReservationState,
    RoleCode,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Timestamped:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow, nullable=False
    )


class Role(Base):
    __tablename__ = "roles"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[RoleCode] = mapped_column(Enum(RoleCode), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)


class Employee(Base, Timestamped):
    __tablename__ = "employees"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30))
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    account: Mapped["UserAccount | None"] = relationship(back_populates="employee", uselist=False)


class UserAccount(Base, Timestamped):
    __tablename__ = "user_accounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), unique=True)
    role_id: Mapped[int] = mapped_column(ForeignKey("roles.id"), nullable=False)
    username: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    employee: Mapped[Employee] = relationship(back_populates="account")
    role: Mapped[Role] = relationship()


class Shift(Base, Timestamped):
    __tablename__ = "shifts"
    id: Mapped[int] = mapped_column(primary_key=True)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    opening_cash: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    closing_cash: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    employee: Mapped[Employee] = relationship()


class Customer(Base, Timestamped):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    full_name: Mapped[str] = mapped_column(String(160), nullable=False)
    phone: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(255))
    reputation_score: Mapped[int] = mapped_column(Integer, default=80, nullable=False)
    email_opt_in: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    sms_opt_in: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class PremiumMembership(Base, Timestamped):
    __tablename__ = "premium_memberships"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    price_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    customer: Mapped[Customer] = relationship()


class ReputationEvent(Base, Timestamped):
    __tablename__ = "reputation_events"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    delta: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(255), nullable=False)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))


class Show(Base, Timestamped):
    __tablename__ = "shows"
    id: Mapped[int] = mapped_column(primary_key=True)
    tmdb_id: Mapped[int | None] = mapped_column(Integer, unique=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    overview: Mapped[str | None] = mapped_column(Text)
    poster_path: Mapped[str | None] = mapped_column(String(500))
    vote_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    seasons: Mapped[list["Season"]] = relationship(back_populates="show", cascade="all, delete-orphan")


class Season(Base):
    __tablename__ = "seasons"
    id: Mapped[int] = mapped_column(primary_key=True)
    show_id: Mapped[int] = mapped_column(ForeignKey("shows.id"), nullable=False)
    season_number: Mapped[int] = mapped_column(Integer, nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    show: Mapped[Show] = relationship(back_populates="seasons")
    __table_args__ = (UniqueConstraint("show_id", "season_number", name="uq_season_show_number"),)


class CatalogItem(Base, Timestamped):
    __tablename__ = "catalog_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_type: Mapped[ItemType] = mapped_column(Enum(ItemType), nullable=False)
    tmdb_id: Mapped[int | None] = mapped_column(Integer)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    overview: Mapped[str | None] = mapped_column(Text)
    release_date: Mapped[date | None] = mapped_column(Date)
    runtime_minutes: Mapped[int | None] = mapped_column(Integer)
    vote_average: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    certification: Mapped[str | None] = mapped_column(String(30))
    poster_path: Mapped[str | None] = mapped_column(String(500))
    rental_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("25000"), nullable=False)
    sale_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("200000"), nullable=False)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("150000"), nullable=False)
    replacement_value: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=Decimal("250000"), nullable=False)
    can_rent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_sell: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    show_id: Mapped[int | None] = mapped_column(ForeignKey("shows.id"))
    season_id: Mapped[int | None] = mapped_column(ForeignKey("seasons.id"))
    episode_number: Mapped[int | None] = mapped_column(Integer)
    archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    show: Mapped[Show | None] = relationship()
    season: Mapped[Season | None] = relationship()
    copies: Mapped[list["PhysicalCopy"]] = relationship(back_populates="item", cascade="all, delete-orphan")
    __table_args__ = (
        UniqueConstraint("item_type", "tmdb_id", name="uq_catalog_item_type_tmdb"),
        Index("ix_catalog_item_title", "title"),
        Index("ix_catalog_show_episode", "show_id", "season_id", "episode_number"),
    )


class Genre(Base):
    __tablename__ = "genres"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)


class ItemGenre(Base):
    __tablename__ = "item_genres"
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), primary_key=True)
    genre_id: Mapped[int] = mapped_column(ForeignKey("genres.id"), primary_key=True)


class ExternalReview(Base, Timestamped):
    __tablename__ = "external_reviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int | None] = mapped_column(ForeignKey("catalog_items.id"))
    show_id: Mapped[int | None] = mapped_column(ForeignKey("shows.id"))
    tmdb_review_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    author: Mapped[str | None] = mapped_column(String(160))
    rating: Mapped[Decimal | None] = mapped_column(Numeric(4, 2))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class PhysicalCopy(Base, Timestamped):
    __tablename__ = "physical_copies"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), nullable=False)
    barcode: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    media_format: Mapped[str] = mapped_column(String(20), default="DVD", nullable=False)
    condition: Mapped[CopyCondition] = mapped_column(Enum(CopyCondition), default=CopyCondition.GOOD)
    status: Mapped[CopyStatus] = mapped_column(Enum(CopyStatus), default=CopyStatus.AVAILABLE, nullable=False)
    can_rent: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    can_sell: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    rental_price_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    sale_price_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    deposit_override: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    item: Mapped[CatalogItem] = relationship(back_populates="copies")
    __table_args__ = (Index("ix_copy_item_status", "item_id", "status"),)


class CopyStatusHistory(Base):
    __tablename__ = "copy_status_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    copy_id: Mapped[int] = mapped_column(ForeignKey("physical_copies.id"), nullable=False)
    from_status: Mapped[CopyStatus | None] = mapped_column(Enum(CopyStatus))
    to_status: Mapped[CopyStatus] = mapped_column(Enum(CopyStatus), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Voucher(Base, Timestamped):
    __tablename__ = "vouchers"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    percent_off: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    amount_off: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    starts_on: Mapped[date | None] = mapped_column(Date)
    ends_on: Mapped[date | None] = mapped_column(Date)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Combo(Base, Timestamped):
    __tablename__ = "combos"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(40), default="FIXED")
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    show_id: Mapped[int | None] = mapped_column(ForeignKey("shows.id"))
    required_count: Mapped[int | None] = mapped_column(Integer)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ComboItem(Base):
    __tablename__ = "combo_items"
    combo_id: Mapped[int] = mapped_column(ForeignKey("combos.id"), primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), primary_key=True)


class Order(Base, Timestamped):
    __tablename__ = "orders"
    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(30), unique=True, nullable=False)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    shift_id: Mapped[int | None] = mapped_column(ForeignKey("shifts.id"))
    status: Mapped[str] = mapped_column(String(30), default="CONFIRMED")
    gross_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    deposit_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    customer: Mapped[Customer] = relationship()
    employee: Mapped[Employee] = relationship()
    lines: Mapped[list["OrderLine"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    __table_args__ = (Index("ix_order_customer_created", "customer_id", "created_at"),)


class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    copy_id: Mapped[int | None] = mapped_column(ForeignKey("physical_copies.id"))
    action: Mapped[LineAction] = mapped_column(Enum(LineAction), nullable=False)
    title_snapshot: Mapped[str] = mapped_column(String(255), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    discount_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    deposit_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    source_rental_line_id: Mapped[int | None] = mapped_column(ForeignKey("order_lines.id"))
    order: Mapped[Order] = relationship(back_populates="lines", foreign_keys=[order_id])
    copy: Mapped[PhysicalCopy | None] = relationship(foreign_keys=[copy_id])


class RentalTerm(Base):
    __tablename__ = "rental_terms"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), unique=True, nullable=False)
    due_date: Mapped[date] = mapped_column(Date, nullable=False)
    state: Mapped[RentalState] = mapped_column(Enum(RentalState), default=RentalState.ACTIVE)
    late_daily_rate: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=5000)
    issued_condition: Mapped[CopyCondition] = mapped_column(Enum(CopyCondition), default=CopyCondition.GOOD)
    returned_on: Mapped[date | None] = mapped_column(Date)
    line: Mapped[OrderLine] = relationship()
    __table_args__ = (Index("ix_rental_due_state", "due_date", "state"),)


class RentalExtension(Base, Timestamped):
    __tablename__ = "rental_extensions"
    id: Mapped[int] = mapped_column(primary_key=True)
    rental_term_id: Mapped[int] = mapped_column(ForeignKey("rental_terms.id"), nullable=False)
    old_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    new_due_date: Mapped[date] = mapped_column(Date, nullable=False)
    fee: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)


class ReturnReceipt(Base, Timestamped):
    __tablename__ = "return_receipts"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    returned_on: Mapped[date] = mapped_column(Date, nullable=False)


class ReturnLine(Base):
    __tablename__ = "return_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    receipt_id: Mapped[int] = mapped_column(ForeignKey("return_receipts.id"), nullable=False)
    rental_term_id: Mapped[int] = mapped_column(ForeignKey("rental_terms.id"), nullable=False)
    outcome: Mapped[str] = mapped_column(String(30), default="NORMAL")
    note: Mapped[str | None] = mapped_column(Text)


class PenaltyCharge(Base, Timestamped):
    __tablename__ = "penalty_charges"
    id: Mapped[int] = mapped_column(primary_key=True)
    rental_term_id: Mapped[int] = mapped_column(ForeignKey("rental_terms.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)


class PaymentTransaction(Base, Timestamped):
    __tablename__ = "payment_transactions"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int | None] = mapped_column(ForeignKey("orders.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    employee_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    method: Mapped[PaymentMethod] = mapped_column(Enum(PaymentMethod), nullable=False)
    category: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(String(500))


class OrderDiscount(Base):
    __tablename__ = "order_discounts"
    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("orders.id"), nullable=False)
    source: Mapped[str] = mapped_column(String(30), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    source_code: Mapped[str | None] = mapped_column(String(80))


class SaleReturn(Base, Timestamped):
    __tablename__ = "sale_returns"
    id: Mapped[int] = mapped_column(primary_key=True)
    sale_line_id: Mapped[int] = mapped_column(ForeignKey("order_lines.id"), nullable=False)
    employee_id: Mapped[int] = mapped_column(ForeignKey("employees.id"), nullable=False)
    returned_on: Mapped[date] = mapped_column(Date, nullable=False)
    refund_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)


class Reservation(Base, Timestamped):
    __tablename__ = "reservations"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), nullable=False)
    state: Mapped[ReservationState] = mapped_column(Enum(ReservationState), default=ReservationState.WAITING)
    hold_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    allocated_copy_id: Mapped[int | None] = mapped_column(ForeignKey("physical_copies.id"))
    __table_args__ = (Index("ix_reservation_item_state_created", "item_id", "state", "created_at"),)


class NotificationOutbox(Base, Timestamped):
    __tablename__ = "notification_outbox"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), nullable=False)
    rental_term_id: Mapped[int | None] = mapped_column(ForeignKey("rental_terms.id"))
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    event: Mapped[str] = mapped_column(String(30), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[NotificationStatus] = mapped_column(Enum(NotificationStatus), default=NotificationStatus.PENDING)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    dedupe_key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)


class ImportRun(Base, Timestamped):
    __tablename__ = "import_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    status: Mapped[str] = mapped_column(String(30), default="RUNNING")
    checkpoint: Mapped[dict | None] = mapped_column(JSON)
    imported_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)


class ContentEmbedding(Base, Timestamped):
    __tablename__ = "content_embeddings"
    id: Mapped[int] = mapped_column(primary_key=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("catalog_items.id"), unique=True, nullable=False)
    model: Mapped[str] = mapped_column(String(80), nullable=False)
    dimensions: Mapped[int] = mapped_column(Integer, nullable=False)
    vector: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class RecommendationCache(Base, Timestamped):
    __tablename__ = "recommendation_cache"
    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("customers.id"))
    cache_key: Mapped[str] = mapped_column(String(160), unique=True, nullable=False)
    item_ids: Mapped[list] = mapped_column(JSON, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DepositDefault(Base, Timestamped):
    """Default deposit by physical media format.

    Individual copies may still use ``deposit_override``.  Keeping these values
    in MySQL (rather than a local preference file) makes the policy durable and
    visible to every packaged installation pointed at the same store database.
    """

    __tablename__ = "deposit_defaults"
    media_format: Mapped[str] = mapped_column(String(20), primary_key=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))


class MockDailyRun(Base):
    """Idempotency marker for an administrator-triggered demo-data run."""

    __tablename__ = "mock_daily_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    business_date: Mapped[date] = mapped_column(Date, unique=True, nullable=False)
    seed_version: Mapped[str] = mapped_column(String(40), nullable=False)
    stats: Mapped[dict | None] = mapped_column(JSON)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_id: Mapped[int | None] = mapped_column(ForeignKey("employees.id"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(100), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(100), nullable=False)
    detail: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    __table_args__ = (
        Index("ix_audit_logs_created_at", "created_at"),
        Index("ix_audit_logs_actor_created", "actor_id", "created_at"),
        Index("ix_audit_logs_action_created", "action", "created_at"),
    )


def engine_from_url(url: str):
    return create_engine(url, pool_pre_ping=True, future=True)


def session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(engine_from_url(url), expire_on_commit=False, class_=Session)


def create_schema(url: str) -> None:
    # The database itself is created by bootstrap; this only owns NormaStore tables.
    Base.metadata.create_all(engine_from_url(url))


class UnitOfWork:
    def __init__(self, factory: sessionmaker[Session]):
        self.factory = factory
        self.session: Session | None = None

    def __enter__(self) -> "UnitOfWork":
        self.session = self.factory()
        return self

    def __exit__(self, exc_type, exc, _tb) -> None:
        assert self.session is not None
        if exc_type:
            self.session.rollback()
        else:
            self.session.commit()
        self.session.close()
