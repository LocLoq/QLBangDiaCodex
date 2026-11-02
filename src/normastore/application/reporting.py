from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal


from normastore.domain.enums import (
    CopyStatus,
    LineAction,
    NotificationStatus,
)
from normastore.domain.policies import late_fee
from normastore.infrastructure.database.models import (
    RentalTerm,
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
    repository,
    today: date | None = None,
    start_on: date | None = None,
    end_on: date | None = None,
) -> OperationalReport:
    today = today or date.today()
    if start_on and end_on and end_on < start_on:
        raise ValueError("Ngày kết thúc không được trước ngày bắt đầu.")

    rental_revenue = (repository.line_revenue(LineAction.RENT) or Decimal("0"))
    rental_revenue += repository.extension_revenue() or Decimal("0")
    sale_revenue = repository.line_revenue(LineAction.BUY) or Decimal("0")
    premium_revenue = repository.premium_revenue() or Decimal("0")
    cash_collected = repository.cash_collected() or Decimal("0")
    cash_refunded = repository.cash_refunded() or Decimal("0")
    gross_revenue, discounts_granted = repository.order_totals()
    average_discount_rate = (
        Decimal(discounts_granted) * Decimal("100") / Decimal(gross_revenue)
        if gross_revenue else Decimal("0")
    )
    active, expired = repository.premium_counts(today)
    active_premium_memberships = int(active or 0)
    expired_premium_memberships = int(expired or 0)
    notification_counts = {
        (channel, status): int(count)
        for channel, status, count in repository.notification_counts()
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
        int(count) for (_channel, status), count in notification_counts.items()
        if status == NotificationStatus.FAILED.value
    )
    penalties = repository.penalties() or Decimal("0")
    refunds = repository.sale_refunds() or Decimal("0")
    deposits_held = repository.deposits_held() or Decimal("0")
    status_counts = Counter(dict(repository.status_counts()))
    top_rentals = tuple((str(title), int(count)) for title, count in repository.top_titles(LineAction.RENT))
    top_sales = tuple((str(title), int(count)) for title, count in repository.top_titles(LineAction.BUY))
    combo_counts: Counter[int] = Counter()
    for source_code in repository.combo_codes():
        for raw_id in (source_code or "").split(","):
            if raw_id.isdigit():
                combo_counts[int(raw_id)] += 1
    combo_names = dict(repository.combo_names(combo_counts)) if combo_counts else {}
    top_combos = tuple(
        (combo_names[combo_id], count)
        for combo_id, count in combo_counts.most_common(10)
        if combo_id in combo_names
    )
    top_vouchers = tuple((str(code), int(count)) for code, count in repository.top_vouchers())
    discounts_by_source = tuple((str(source), Decimal(amount)) for source, amount in repository.discounts_by_source())
    premium_customer_count = active_premium_memberships
    stock_rows = repository.stock_rows()
    stockout_ids = [item_id for item_id, _title, count in stock_rows if not int(count)]
    eta_by_item = dict(repository.stock_eta(stockout_ids)) if stockout_ids else {}
    out_of_stock = tuple(
        StockoutItem(str(title), eta_by_item.get(item_id))
        for item_id, title, available_count in stock_rows if not int(available_count)
    )[:20]
    waiting_reservations = tuple(
        (str(title), int(count)) for title, count in repository.waiting_reservations()
    )
    overdue_rows = repository.overdue_rows(today)
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
