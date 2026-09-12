from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from normastore.domain.enums import (
    CopyStatus,
    LineAction,
    NotificationStatus,
    RentalState,
    ReservationState,
)
from normastore.domain.policies import late_fee
from normastore.infrastructure.database import (
    CatalogItem,
    Combo,
    Customer,
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
    SaleReturn,
)


@dataclass(frozen=True)
class OverdueCustomer:
    customer_name: str
    rental_count: int
    overdue_amount: Decimal


@dataclass(frozen=True)
class StockoutItem:
    title: str
    estimated_available_on: date | None


@dataclass(frozen=True)
class OperationalReport:
    rental_revenue: Decimal
    sale_revenue: Decimal
    premium_revenue: Decimal
    cash_collected: Decimal
    cash_refunded: Decimal
    net_cash_flow: Decimal
    gross_revenue: Decimal
    discounts_granted: Decimal
    average_discount_rate: Decimal
    active_premium_memberships: int
    expired_premium_memberships: int
    email_notifications_sent: int
    sms_notifications_sent: int
    notification_failures: int
    penalties_assessed: Decimal
    sales_refunded: Decimal
    deposits_held: Decimal
    available: int
    rented: int
    inspection: int
    repair: int
    lost: int
    retired: int
    overdue_count: int
    top_rentals: tuple[tuple[str, int], ...]
    top_sales: tuple[tuple[str, int], ...]
    top_combos: tuple[tuple[str, int], ...]
    top_vouchers: tuple[tuple[str, int], ...]
    discounts_by_source: tuple[tuple[str, Decimal], ...]
    premium_customer_count: int
    out_of_stock: tuple[StockoutItem, ...]
    waiting_reservations: tuple[tuple[str, int], ...]
    overdue_customers: tuple[OverdueCustomer, ...]


def operational_report(
    session: Session,
    today: date | None = None,
    start_on: date | None = None,
    end_on: date | None = None,
) -> OperationalReport:
    today = today or date.today()
    if start_on and end_on and end_on < start_on:
        raise ValueError("Ngày kết thúc không được trước ngày bắt đầu.")

    def in_period(column):
        conditions = []
        if start_on:
            conditions.append(func.date(column) >= start_on)
        if end_on:
            conditions.append(func.date(column) <= end_on)
        return conditions

    order_period = in_period(Order.created_at)
    rental_revenue = session.scalar(
        select(func.coalesce(func.sum(OrderLine.unit_price - OrderLine.discount_amount), 0))
        .join(Order, OrderLine.order_id == Order.id)
        .where(OrderLine.action == LineAction.RENT, *order_period)
    ) or Decimal("0")
    rental_revenue += session.scalar(
        select(func.coalesce(func.sum(RentalExtension.fee), 0)).where(*in_period(RentalExtension.created_at))
    ) or Decimal("0")
    sale_revenue = session.scalar(
        select(func.coalesce(func.sum(OrderLine.unit_price - OrderLine.discount_amount), 0))
        .join(Order, OrderLine.order_id == Order.id)
        .where(OrderLine.action == LineAction.BUY, *order_period)
    ) or Decimal("0")
    premium_revenue = session.scalar(
        select(func.coalesce(func.sum(PremiumMembership.price_paid), 0))
        .where(*in_period(PremiumMembership.created_at))
    ) or Decimal("0")
    payment_period = in_period(PaymentTransaction.created_at)
    cash_collected = session.scalar(
        select(func.coalesce(func.sum(PaymentTransaction.amount), 0))
        .where(PaymentTransaction.amount > 0, *payment_period)
    ) or Decimal("0")
    cash_refunded = session.scalar(
        select(func.coalesce(-func.sum(PaymentTransaction.amount), 0))
        .where(PaymentTransaction.amount < 0, *payment_period)
    ) or Decimal("0")
    gross_revenue = session.scalar(
        select(func.coalesce(func.sum(Order.gross_total), 0)).where(*order_period)
    ) or Decimal("0")
    discounts_granted = session.scalar(
        select(func.coalesce(func.sum(Order.discount_total), 0)).where(*order_period)
    ) or Decimal("0")
    average_discount_rate = (
        Decimal(discounts_granted) * Decimal("100") / Decimal(gross_revenue)
        if gross_revenue else Decimal("0")
    )
    active_premium_memberships = int(session.scalar(
        select(func.count(func.distinct(PremiumMembership.customer_id))).where(
            PremiumMembership.starts_on <= today,
            PremiumMembership.ends_on >= today,
        )
    ) or 0)
    expired_premium_memberships = int(session.scalar(
        select(func.count(func.distinct(PremiumMembership.customer_id))).where(PremiumMembership.ends_on < today)
    ) or 0)
    notification_counts = {
        (channel, status): int(count)
        for channel, status, count in session.execute(
            select(NotificationOutbox.channel, NotificationOutbox.status, func.count(NotificationOutbox.id))
            .where(*in_period(NotificationOutbox.scheduled_for))
            .group_by(NotificationOutbox.channel, NotificationOutbox.status)
        ).all()
    }
    email_notifications_sent = sum(
        count for (channel, status), count in notification_counts.items()
        if channel == "EMAIL" and status == NotificationStatus.SENT.value
    )
    sms_notifications_sent = sum(
        count for (channel, status), count in notification_counts.items()
        if channel == "SMS" and status == NotificationStatus.SENT.value
    )
    notification_failures = sum(
        int(count)
        for (_channel, status), count in notification_counts.items()
        if status == NotificationStatus.FAILED.value
    )
    penalties = session.scalar(
        select(func.coalesce(func.sum(PenaltyCharge.amount), 0)).where(*in_period(PenaltyCharge.created_at))
    ) or Decimal("0")
    refunds = session.scalar(
        select(func.coalesce(func.sum(SaleReturn.refund_amount), 0)).where(*in_period(SaleReturn.returned_on))
    ) or Decimal("0")
    deposits_held = session.scalar(
        select(func.coalesce(func.sum(OrderLine.deposit_amount), 0))
        .join(RentalTerm, RentalTerm.line_id == OrderLine.id)
        .where(RentalTerm.state == RentalState.ACTIVE)
    ) or Decimal("0")
    status_counts = Counter(
        dict(session.execute(select(PhysicalCopy.status, func.count(PhysicalCopy.id)).group_by(PhysicalCopy.status)).all())
    )
    top_rentals = tuple(
        (str(title), int(count))
        for title, count in session.execute(
            select(OrderLine.title_snapshot, func.count(OrderLine.id))
            .join(Order, OrderLine.order_id == Order.id)
            .where(OrderLine.action == LineAction.RENT, *order_period)
            .group_by(OrderLine.title_snapshot)
            .order_by(func.count(OrderLine.id).desc(), OrderLine.title_snapshot)
            .limit(10)
        ).all()
    )
    top_sales = tuple(
        (str(title), int(count))
        for title, count in session.execute(
            select(OrderLine.title_snapshot, func.count(OrderLine.id))
            .join(Order, OrderLine.order_id == Order.id)
            .where(OrderLine.action == LineAction.BUY, *order_period)
            .group_by(OrderLine.title_snapshot)
            .order_by(func.count(OrderLine.id).desc(), OrderLine.title_snapshot)
            .limit(10)
        ).all()
    )
    combo_counts: Counter[int] = Counter()
    for source_code in session.scalars(
        select(OrderDiscount.source_code)
        .join(Order, OrderDiscount.order_id == Order.id)
        .where(OrderDiscount.source == "COMBO", *order_period)
    ):
        for raw_id in (source_code or "").split(","):
            if raw_id.isdigit():
                combo_counts[int(raw_id)] += 1
    combo_names = dict(
        session.execute(select(Combo.id, Combo.name).where(Combo.id.in_(combo_counts))).all()
    ) if combo_counts else {}
    top_combos = tuple(
        (combo_names[combo_id], count)
        for combo_id, count in combo_counts.most_common(10)
        if combo_id in combo_names
    )
    top_vouchers = tuple(
        (str(code), int(count))
        for code, count in session.execute(
            select(OrderDiscount.source_code, func.count(OrderDiscount.id))
            .join(Order, OrderDiscount.order_id == Order.id)
            .where(OrderDiscount.source == "VOUCHER", OrderDiscount.source_code.is_not(None), *order_period)
            .group_by(OrderDiscount.source_code)
            .order_by(func.count(OrderDiscount.id).desc(), OrderDiscount.source_code)
            .limit(10)
        ).all()
    )
    discounts_by_source = tuple(
        (str(source), Decimal(amount))
        for source, amount in session.execute(
            select(OrderDiscount.source, func.coalesce(func.sum(OrderDiscount.amount), 0))
            .join(Order, OrderDiscount.order_id == Order.id)
            .where(*order_period)
            .group_by(OrderDiscount.source)
            .order_by(func.sum(OrderDiscount.amount).desc())
        ).all()
    )
    premium_customer_count = active_premium_memberships
    stock_rows = session.execute(
        select(
            CatalogItem.id,
            CatalogItem.title,
            func.coalesce(
                func.sum((PhysicalCopy.status == CopyStatus.AVAILABLE) & PhysicalCopy.can_rent),
                0,
            ),
        )
        .outerjoin(PhysicalCopy)
        .where(CatalogItem.archived.is_(False))
        .group_by(CatalogItem.id)
        .order_by(CatalogItem.title)
    ).all()
    stockout_ids = [
        item_id
        for item_id, _title, available_count in stock_rows
        if not int(available_count)
    ]
    eta_by_item = dict(
        session.execute(
            select(PhysicalCopy.item_id, func.min(RentalTerm.due_date))
            .join(OrderLine, OrderLine.copy_id == PhysicalCopy.id)
            .join(RentalTerm, RentalTerm.line_id == OrderLine.id)
            .where(
                PhysicalCopy.item_id.in_(stockout_ids),
                RentalTerm.state == RentalState.ACTIVE,
            )
            .group_by(PhysicalCopy.item_id)
        ).all()
    ) if stockout_ids else {}
    out_of_stock = tuple(
        StockoutItem(str(title), eta_by_item.get(item_id))
        for item_id, title, available_count in stock_rows
        if not int(available_count)
    )[:20]
    waiting_reservations = tuple(
        (str(title), int(count))
        for title, count in session.execute(
            select(CatalogItem.title, func.count(Reservation.id))
            .join(CatalogItem, Reservation.item_id == CatalogItem.id)
            .where(Reservation.state == ReservationState.WAITING)
            .group_by(CatalogItem.id)
            .order_by(func.count(Reservation.id).desc(), CatalogItem.title)
            .limit(20)
        ).all()
    )
    overdue_rows = session.execute(
        select(RentalTerm, Customer)
        .join(OrderLine, RentalTerm.line_id == OrderLine.id)
        .join(Order, OrderLine.order_id == Order.id)
        .join(Customer, Order.customer_id == Customer.id)
        .where(RentalTerm.state == RentalState.ACTIVE, RentalTerm.due_date < today)
    ).all()
    overdue_by_customer: dict[tuple[int, str], list[RentalTerm]] = defaultdict(list)
    for term, customer in overdue_rows:
        overdue_by_customer[(customer.id, customer.full_name)].append(term)
    overdue_count = sum(len(terms) for terms in overdue_by_customer.values())
    overdue_customers = tuple(
        sorted(
            (
                OverdueCustomer(
                    customer_name=name,
                    rental_count=len(terms),
                    overdue_amount=sum(
                        (late_fee(term.due_date, today, Decimal(term.late_daily_rate)) for term in terms),
                        Decimal("0"),
                    ),
                )
                for (_customer_id, name), terms in overdue_by_customer.items()
            ),
            key=lambda entry: entry.overdue_amount,
            reverse=True,
        )[:20]
    )
    return OperationalReport(
        rental_revenue=Decimal(rental_revenue),
        sale_revenue=Decimal(sale_revenue),
        premium_revenue=Decimal(premium_revenue),
        cash_collected=Decimal(cash_collected),
        cash_refunded=Decimal(cash_refunded),
        net_cash_flow=Decimal(cash_collected) - Decimal(cash_refunded),
        gross_revenue=Decimal(gross_revenue),
        discounts_granted=Decimal(discounts_granted),
        average_discount_rate=average_discount_rate,
        active_premium_memberships=active_premium_memberships,
        expired_premium_memberships=expired_premium_memberships,
        email_notifications_sent=email_notifications_sent,
        sms_notifications_sent=sms_notifications_sent,
        notification_failures=notification_failures,
        penalties_assessed=Decimal(penalties),
        sales_refunded=Decimal(refunds),
        deposits_held=Decimal(deposits_held),
        available=int(status_counts[CopyStatus.AVAILABLE]),
        rented=int(status_counts[CopyStatus.RENTED]),
        inspection=int(status_counts[CopyStatus.INSPECTION]),
        repair=int(status_counts[CopyStatus.REPAIR]),
        lost=int(status_counts[CopyStatus.LOST]),
        retired=int(status_counts[CopyStatus.RETIRED]),
        overdue_count=overdue_count,
        top_rentals=top_rentals,
        top_sales=top_sales,
        top_combos=top_combos,
        top_vouchers=top_vouchers,
        discounts_by_source=discounts_by_source,
        premium_customer_count=premium_customer_count,
        out_of_stock=out_of_stock,
        waiting_reservations=waiting_reservations,
        overdue_customers=overdue_customers,
    )
