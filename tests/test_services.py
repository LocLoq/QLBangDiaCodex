from datetime import date, datetime, timedelta, timezone
from dataclasses import replace
from decimal import Decimal

import numpy as np
import pytest

from normastore.application.ai_search import search_local
from normastore.application.contracts import BusinessError, CatalogFilters, CheckoutLine, PageRequest, PaymentInput, RentalReturnInput, SortSpec, UpdateInventoryCopyRequest
from normastore.application._operations import _StoreOperations
from normastore.domain.enums import (
    CopyCondition,
    CopyStatus,
    LineAction,
    NotificationStatus,
    PaymentMethod,
    ReturnOutcome,
    RoleCode,
)
from normastore.infrastructure.database.models import (
    CatalogItem,
    ContentEmbedding,
    Employee,
    ExternalReview,
    Genre,
    ItemGenre,
    NotificationOutbox,
    OrderDiscount,
    OrderLine,
    PaymentTransaction,
    PremiumMembership,
    PenaltyCharge,
    RentalExtension,
    RentalTerm,
)
from normastore.jobs import process_notification_outbox
from normastore.infrastructure.database.repositories.notifications import NotificationQueries
from normastore.infrastructure.database.repositories.search import SearchRepository


def manager_id(session) -> int:
    return session.query(Employee.id).first()[0]


def test_quote_requires_due_date(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE")
    quote = service.quote(customer.id, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))])
    assert quote.deposit > 0


def test_list_customers_filters_by_name_or_phone(session):
    service = _StoreOperations(session)
    customer = service.add_customer("Le Hoang Phuc", "0999888777")

    assert [row.id for row in service.list_customers("Hoang Phuc")] == [customer.id]
    assert [row.id for row in service.list_customers("88877")] == [customer.id]


def test_query_orders_filters_customer_and_business_date(session):
    service = _StoreOperations(session)
    customer = service.add_customer("Le Hoang Phuc", "0999888777")
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE" and copy.can_sell)
    order = service.checkout(customer.id, manager_id(session), [CheckoutLine(copy.id, LineAction.BUY)], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    order.created_at = datetime(2026, 1, 1, 17, 0, tzinfo=timezone.utc)
    session.flush()

    assert [row.order_id for row in service.query_orders("Hoang Phuc", start_on=date(2026, 1, 2), end_on=date(2026, 1, 2)).items] == [order.id]
    assert [row.order_id for row in service.query_orders("88877", start_on=date(2026, 1, 2)).items] == [order.id]
    assert not service.query_orders("88877", end_on=date(2026, 1, 1)).items


def test_active_rentals_lists_checked_out_copy(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE")
    employee_id = session.query(Employee.id).first()[0]
    service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    session.flush()

    rentals = service.active_rentals()

    assert any(rental.barcode == copy.barcode and rental.customer_id == customer.id for rental in rentals)
    session.rollback()


def test_returnable_sales_only_includes_recent_sold_copy(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE" and copy.can_sell)
    employee_id = session.query(Employee.id).first()[0]
    service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.BUY)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    session.flush()

    sales = service.returnable_sales()

    assert any(sale.barcode == copy.barcode and sale.customer_name == customer.full_name for sale in sales)
    session.rollback()


def test_rental_to_sale_marks_copy_sold_and_applies_deposit(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE" and copy.can_sell)
    employee_id = session.query(Employee.id).first()[0]
    service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    session.flush()
    term = session.query(RentalTerm).filter_by(line_id=session.query(RentalTerm.line_id).order_by(RentalTerm.id.desc()).first()[0]).first()

    sale = service.rental_to_sale(term.id, employee_id, PaymentInput(PaymentMethod.CASH, Decimal("0")))
    session.flush()

    assert term.state.value == "PURCHASED"
    assert copy.status.value == "SOLD"
    assert sale.discount_total == 0
    assert sale.deposit_applied == term.line.deposit_amount
    assert sale.status == "PARTIALLY_PAID"
    session.rollback()


@pytest.mark.parametrize("legacy", [False, True])
def test_converted_sale_treats_deposit_as_payment_and_preserves_refund(session, legacy):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Cấn cọc mua đĩa", rental_price=Decimal("20000"), sale_price=Decimal("100000"))
    copy = service.add_copy(item.id, f"CONVERT-CREDIT-{legacy}", actor_id=actor)
    service.save_deposit_percent(Decimal("75"), actor)
    lines = [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))]
    quote = service.quote(customer.id, lines)
    rental = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    term = session.query(RentalTerm).filter(RentalTerm.line.has(order_id=rental.id)).one()
    before = service.operational_report()
    sale = service.rental_to_sale(term.id, actor, PaymentInput(PaymentMethod.CASH, Decimal("25000")))
    session.flush()
    if legacy:
        sale.deposit_applied = None
        sale.discount_total = Decimal("75000")
        sale.lines[0].discount_amount = Decimal("75000")
        session.flush()
    report = service.operational_report()
    receipt = service.order_receipt(sale.id)
    assert report.sale_revenue - before.sale_revenue == Decimal("100000")
    assert report.discounts_granted == before.discounts_granted
    assert receipt.applied_deposit == Decimal("75000")
    assert receipt.discount_total == 0 and receipt.lines[0].discount_amount == 0
    assert receipt.total_due == receipt.checkout_paid == Decimal("25000") and receipt.balance_due == 0
    assert service.order_detail(sale.id)[0].total_due == Decimal("25000")
    assert service.query_orders(sale.code).items[0].total_due == Decimal("25000")
    assert service.return_sale(sale.lines[0].id, actor) == Decimal("100000")
    session.flush()
    assert service.operational_report().net_cash_flow - before.net_cash_flow == Decimal("-75000")
    session.rollback()


def test_converted_sale_partial_payment_and_excess_deposit(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Cấn cọc có chênh lệch", sale_price=Decimal("100000"))
    service.save_deposit_percent(Decimal("75"), actor)
    first = service.add_copy(item.id, "CONVERT-PARTIAL", actor_id=actor)
    second = service.add_copy(item.id, "CONVERT-EXCESS", actor_id=actor)
    lines = [CheckoutLine(first.id, LineAction.RENT, date.today() + timedelta(days=3)), CheckoutLine(second.id, LineAction.RENT, date.today() + timedelta(days=3))]
    quote = service.quote(customer.id, lines)
    rental = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    terms = {term.line.copy_id: term for term in session.query(RentalTerm).filter(RentalTerm.line.has(order_id=rental.id))}
    partial = service.rental_to_sale(terms[first.id].id, actor, PaymentInput(PaymentMethod.CASH, Decimal("10000")))
    session.flush()
    assert partial.status == "PARTIALLY_PAID"
    assert service.order_receipt(partial.id).balance_due == Decimal("15000")
    assert service.return_sale(partial.lines[0].id, actor) == Decimal("85000")
    service.update_inventory_copy(second.id, UpdateInventoryCopyRequest(second.barcode, "DVD", CopyCondition.GOOD, True, True,
                                  CopyStatus.RENTED, sale_price_override=Decimal("50000"), sale_price_mode="DIRECT"), actor)
    excess = service.rental_to_sale(terms[second.id].id, actor, PaymentInput(PaymentMethod.CASH, Decimal("0")))
    session.flush()
    assert excess.deposit_applied == Decimal("50000")
    refund = session.query(PaymentTransaction).filter_by(order_id=excess.id, category="DEPOSIT_REFUND").one()
    assert refund.amount == Decimal("-25000")
    assert service.return_sale(excess.lines[0].id, actor) == Decimal("50000")
    session.rollback()


def test_rental_to_sale_rejects_unconfirmed_deposit_on_unpaid_rental(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phiếu thuê chưa thu cọc")
    copy = service.add_copy(item.id, "UNPAID-DEPOSIT", actor_id=actor)
    rental = service.checkout(customer.id, actor, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
                              [PaymentInput(PaymentMethod.CASH, Decimal("0"))])
    session.flush()
    term = session.query(RentalTerm).filter(RentalTerm.line.has(order_id=rental.id)).one()
    with pytest.raises(BusinessError, match="chưa thanh toán đủ"):
        service.rental_to_sale(term.id, actor, PaymentInput(PaymentMethod.CASH, Decimal("0")))
    assert term.state.value == "ACTIVE" and copy.status == CopyStatus.RENTED
    session.rollback()


def test_returned_sale_cannot_be_refunded_again_after_disc_is_resold(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim hoàn rồi bán lại", sale_price=Decimal("100000"))
    copy = service.add_copy(item.id, "REFUND-ONCE", actor_id=actor)
    lines = [CheckoutLine(copy.id, LineAction.BUY)]
    first = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, Decimal("100000"))])
    session.flush()
    first_line_id = first.lines[0].id
    assert service.return_sale(first_line_id, actor) == Decimal("100000")
    service.inspect_copy(copy.id, actor, CopyStatus.AVAILABLE)
    second = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, Decimal("100000"))])
    session.flush()
    assert first_line_id not in {sale.line_id for sale in service.returnable_sales()}
    assert second.lines[0].id in {sale.line_id for sale in service.returnable_sales()}
    with pytest.raises(BusinessError, match="không còn"):
        service.return_sale(first_line_id, actor)
    session.rollback()


def test_sale_return_moves_copy_to_inspection_and_records_refund(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE" and copy.can_sell)
    employee_id = session.query(Employee.id).first()[0]
    order = service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.BUY)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    session.flush()

    refund = service.return_sale(order.lines[0].id, employee_id)
    session.flush()

    assert refund == order.lines[0].unit_price - order.lines[0].discount_amount
    assert copy.status.value == "INSPECTION"
    session.rollback()


def test_damaged_sale_return_requires_manager_and_can_apply_deduction(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    admin_id = session.query(Employee.id).first()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    order = service.checkout(
        customer.id,
        admin_id,
        
        [CheckoutLine(copy.id, LineAction.BUY)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    staff = service.create_employee_account("Nguyễn Trọng Khang", "0909999010", "khang.staff", RoleCode.STAFF, "matkhau123", admin_id)
    session.flush()

    with pytest.raises(BusinessError, match="Quản lý"):
        service.return_sale(order.lines[0].id, staff.id, condition=CopyCondition.DAMAGED)
    refund = service.return_sale(
        order.lines[0].id,
        admin_id,
        condition=CopyCondition.DAMAGED,
        deduction=Decimal("10000"),
        note="Vỏ đĩa bị nứt",
    )

    assert refund == order.lines[0].unit_price - Decimal("10000")
    assert copy.status == CopyStatus.INSPECTION
    assert copy.condition == CopyCondition.DAMAGED
    session.rollback()


def test_inspection_approves_returned_sale_copy_back_to_inventory(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE" and copy.can_sell)
    employee_id = session.query(Employee.id).first()[0]
    order = service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.BUY)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    session.flush()
    service.return_sale(order.lines[0].id, employee_id)

    service.inspect_copy(copy.id, employee_id, CopyStatus.AVAILABLE, "Đĩa nguyên vẹn")

    assert copy.status == CopyStatus.AVAILABLE
    session.rollback()


def test_expired_hold_releases_copy_and_allocates_next_reservation(session):
    service = _StoreOperations(session)
    customer_one = service.list_customers()[0]
    customer_two = service.add_customer("Lê Ngọc Bích", "0999999001")
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    for candidate in service.catalog_item(item.id).copies:
        if candidate.id != copy.id and candidate.status == CopyStatus.AVAILABLE:
            candidate.status = CopyStatus.REPAIR

    first = service.reserve(customer_one.id, [item.id])[0]
    second = service.reserve(customer_two.id, [item.id])[0]
    session.flush()
    first.hold_until = datetime.now(timezone.utc) - timedelta(seconds=1)

    expired = service.expire_reservation_holds()

    assert expired == 1
    assert first.state.value == "EXPIRED"
    assert second.state.value == "HELD"
    assert copy.status == CopyStatus.HELD
    session.rollback()


def test_notification_worker_sends_only_current_reminder_per_channel(session):
    service = _StoreOperations(session)
    session.query(NotificationOutbox).update({"status": NotificationStatus.SENT})
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=1))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    session.flush()
    term = session.query(RentalTerm).order_by(RentalTerm.id.desc()).first()
    for outbox in session.query(NotificationOutbox).filter_by(rental_term_id=term.id):
        outbox.scheduled_for = datetime.now(timezone.utc) - timedelta(minutes=1)

    delivered: list[tuple[str, str]] = []
    result = process_notification_outbox(
        NotificationQueries(session),
        send_email=lambda recipient, body: delivered.append((recipient, body)),
        send_sms=lambda phone, body: delivered.append((phone, body)),
    )

    assert result.sent == 2
    assert result.skipped == 8
    assert len(delivered) == 2
    report = service.operational_report()
    assert report.email_notifications_sent >= 1
    assert report.sms_notifications_sent >= 1
    assert report.notification_failures == 0
    session.rollback()


def test_operational_report_excludes_active_deposits_from_rental_revenue(session):
    service = _StoreOperations(session)
    before = service.operational_report()
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    quote = service.quote(customer.id, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))])

    service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, quote.total_due)],
    )
    session.flush()
    after = service.operational_report()

    assert after.rental_revenue - before.rental_revenue == item.rental_price
    assert after.deposits_held - before.deposits_held == quote.deposit
    session.rollback()


def test_dashboard_cash_flow_includes_refunds(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    employee_id = session.query(Employee.id).first()[0]
    before = service.dashboard()["cash_flow"]
    session.add_all([
        PaymentTransaction(
            customer_id=customer.id,
            employee_id=employee_id,
            method=PaymentMethod.CASH,
            category="TEST_RECEIPT",
            amount=Decimal("100000"),
        ),
        PaymentTransaction(
            customer_id=customer.id,
            employee_id=employee_id,
            method=PaymentMethod.CASH,
            category="TEST_REFUND",
            amount=Decimal("-25000"),
        ),
    ])
    session.flush()

    assert service.dashboard()["cash_flow"] - before == Decimal("75000")
    session.rollback()


def test_operational_report_includes_net_cash_flow(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    employee_id = session.query(Employee.id).first()[0]
    before = service.operational_report(start_on=date.today(), end_on=date.today())
    session.add_all([
        PaymentTransaction(customer_id=customer.id, employee_id=employee_id, method=PaymentMethod.CASH, category="TEST_RECEIPT", amount=Decimal("100000")),
        PaymentTransaction(customer_id=customer.id, employee_id=employee_id, method=PaymentMethod.CASH, category="TEST_REFUND", amount=Decimal("-25000")),
    ])
    session.flush()
    after = service.operational_report(start_on=date.today(), end_on=date.today())

    assert after.cash_collected - before.cash_collected == Decimal("100000")
    assert after.cash_refunded - before.cash_refunded == Decimal("25000")
    assert after.net_cash_flow - before.net_cash_flow == Decimal("75000")
    session.rollback()


def test_operational_report_lists_sales_stockouts_and_waiting_reservations(session):
    service = _StoreOperations(session)
    customers = service.list_customers()
    employee_id = session.query(Employee.id).first()[0]
    item = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim báo cáo hết hàng")
    copy = service.add_copy(item.id, "DVD-REPORT-SOLD-001", actor_id=manager_id(session))
    rented_item = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim báo cáo có ETA")
    rented_copy = service.add_copy(rented_item.id, "DVD-REPORT-RENT-001", actor_id=manager_id(session))
    eta = date.today() + timedelta(days=7)
    service.checkout(
        customers[0].id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.BUY)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    service.checkout(
        customers[0].id,
        employee_id,
        
        [CheckoutLine(rented_copy.id, LineAction.RENT, eta)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    service.reserve(customers[1].id, [item.id])
    session.flush()

    report = service.operational_report()
    stockouts = {stockout.title: stockout.estimated_available_on for stockout in report.out_of_stock}

    assert (item.title, 1) in report.top_sales
    assert stockouts[item.title] is None
    assert stockouts[rented_item.title] == eta
    assert (item.title, 1) in report.waiting_reservations
    session.rollback()


def test_operational_report_filters_transaction_metrics_by_period(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    employee_id = session.query(Employee.id).first()[0]
    item = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim doanh thu kỳ cũ")
    copy = service.add_copy(item.id, "DVD-REPORT-PERIOD-001", actor_id=manager_id(session))
    order = service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.BUY)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    order.created_at = datetime.now(timezone.utc) - timedelta(days=40)
    session.flush()

    report = service.operational_report(start_on=date.today(), end_on=date.today())

    assert report.sale_revenue == Decimal("0")
    assert (item.title, 1) not in report.top_sales
    with pytest.raises(ValueError, match="kết thúc"):
        service.operational_report(start_on=date.today(), end_on=date.today() - timedelta(days=1))
    session.rollback()


def test_top_customers_uses_order_lines_and_period_without_deposits(session):
    from normastore.infrastructure.database.models import Order

    service = _StoreOperations(session)
    actor = manager_id(session)
    first = service.add_customer("Khách trùng tên", "0987701231")
    second = service.add_customer("Khách trùng tên", "0987701232")
    timestamp = datetime(2021, 3, 15, 12, tzinfo=timezone.utc)
    first_order = Order(code="TOP-CUSTOMER-001", customer_id=first.id, employee_id=actor,
                        gross_total=Decimal("150000"), discount_total=Decimal("10000"),
                        deposit_total=Decimal("500000"), created_at=timestamp)
    second_order = Order(code="TOP-CUSTOMER-002", customer_id=second.id, employee_id=actor,
                         gross_total=Decimal("120000"), discount_total=Decimal("0"),
                         deposit_total=Decimal("0"), created_at=timestamp)
    session.add_all([first_order, second_order])
    session.flush()
    session.add_all([
        OrderLine(order_id=first_order.id, action=LineAction.RENT, title_snapshot="Thuê", unit_price=Decimal("100000"), discount_amount=Decimal("10000")),
        OrderLine(order_id=first_order.id, action=LineAction.PREMIUM, title_snapshot="Hội viên", unit_price=Decimal("50000"), discount_amount=Decimal("0")),
        OrderLine(order_id=second_order.id, action=LineAction.BUY, title_snapshot="Mua", unit_price=Decimal("120000"), discount_amount=Decimal("0")),
    ])
    session.flush()
    report = service.operational_report(start_on=date(2021, 3, 15), end_on=date(2021, 3, 15))
    assert [(row.customer_id, row.order_count, row.total) for row in report.top_customers] == [
        (first.id, 1, Decimal("140000")), (second.id, 1, Decimal("120000")),
    ]
    assert not service.operational_report(start_on=date(2021, 3, 16), end_on=date(2021, 3, 16)).top_customers


def test_operational_report_counts_active_and_expired_premium_memberships(session):
    service = _StoreOperations(session)
    before = service.operational_report()
    active_customer = service.add_customer("Khách Premium mới", "0909100001")
    expired_customer = service.add_customer("Khách Premium cũ", "0909100002")
    service.activate_premium(active_customer.id, 30)
    session.add(PremiumMembership(
        customer_id=expired_customer.id,
        starts_on=date.today() - timedelta(days=60),
        ends_on=date.today() - timedelta(days=1),
        price_paid=Decimal("59000"),
    ))
    session.flush()

    after = service.operational_report()

    assert after.active_premium_memberships == before.active_premium_memberships + 1
    assert after.expired_premium_memberships == before.expired_premium_memberships + 1
    assert after.premium_revenue - before.premium_revenue == Decimal("118000")
    session.rollback()


def test_activate_premium_records_payment(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    employee_id = session.query(Employee.id).first()[0]

    service.activate_premium(customer.id, 90, employee_id, PaymentMethod.BANK_TRANSFER)
    session.flush()

    payment = session.query(PaymentTransaction).filter_by(customer_id=customer.id, category="PREMIUM").order_by(PaymentTransaction.id.desc()).first()
    assert payment is not None
    assert payment.amount == Decimal("159000")
    assert payment.method == PaymentMethod.BANK_TRANSFER
    session.rollback()


def test_bulk_episodes_are_independent_items_grouped_by_show_and_season(session):
    service = _StoreOperations(session)
    show = service.create_show("Những ngày bình yên", actor_id=manager_id(session))

    episodes = service.add_episodes_bulk(show.id, 1, 1, 3, "Chương {number}", manager_id(session))

    assert [episode.episode_number for episode in episodes] == [1, 2, 3]
    assert {episode.show_id for episode in episodes} == {show.id}
    assert len({episode.season_id for episode in episodes}) == 1
    session.rollback()


def test_list_show_episodes_groups_and_filters_by_season(session):
    service = _StoreOperations(session)
    show = service.create_show("Bộ phim chi tiết", actor_id=manager_id(session))
    first, second = service.add_episodes_bulk(show.id, 1, 1, 2, actor_id=manager_id(session))
    third, = service.add_episodes_bulk(show.id, 2, 1, 1, actor_id=manager_id(session))
    service.add_copy(first.id, "DVD-SHOW-DETAIL-001", actor_id=manager_id(session))
    session.flush()

    shows = {entry.show_id: entry for entry in service.list_shows()}
    season_one = service.list_show_episodes(show.id, 1)

    assert shows[show.id].season_count == 2
    assert [entry.item_id for entry in season_one] == [first.id, second.id]
    assert season_one[0].rentable_copies == 1
    assert service.list_show_episodes(show.id)[-1].item_id == third.id
    result = service.query_catalog(CatalogFilters(show_id=show.id))
    assert {row.show_id for row in result.items} == {show.id}
    session.rollback()


def test_premium_then_voucher_discount_is_capped_and_snapshotted(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    service.activate_premium(customer.id, 30)
    service.create_voucher("Giam40", percent_off=Decimal("40"), actor_id=employee_id)

    quote = service.quote(customer.id, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))], "giam40")

    assert quote.discount == item.rental_price * Decimal("0.46")
    assert quote.discount_sources == {"PREMIUM": item.rental_price * Decimal("0.10"), "VOUCHER": item.rental_price * Decimal("0.36")}
    order = service.checkout(
        customer.id,
        employee_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, quote.total_due)],
        "giam40",
    )
    session.flush()
    discounts = session.query(OrderDiscount).filter_by(order_id=order.id).all()
    assert {discount.source for discount in discounts} == {"PREMIUM", "VOUCHER"}
    session.rollback()


def test_checkout_allocates_discount_to_lines_and_sale_return_uses_net_amount(session):
    service = _StoreOperations(session)
    before = service.operational_report()
    customer = service.list_customers()[0]
    employee_id = session.query(Employee.id).first()[0]
    rental = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim thuê giảm giá", rental_price=Decimal("100000"))
    sale = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim bán giảm giá", sale_price=Decimal("200000"))
    rental_copy = service.add_copy(rental.id, "DVD-DISCOUNT-RENT", actor_id=manager_id(session))
    sale_copy = service.add_copy(sale.id, "DVD-DISCOUNT-SALE", actor_id=manager_id(session))
    service.create_voucher("LINE10", percent_off=Decimal("10"), actor_id=employee_id)
    quote = service.quote(
        customer.id,
        [
            CheckoutLine(rental_copy.id, LineAction.RENT, date.today() + timedelta(days=3)),
            CheckoutLine(sale_copy.id, LineAction.BUY),
        ],
        "LINE10",
    )

    order = service.checkout(
        customer.id,
        employee_id,
        
        [
            CheckoutLine(rental_copy.id, LineAction.RENT, date.today() + timedelta(days=3)),
            CheckoutLine(sale_copy.id, LineAction.BUY),
        ],
        [PaymentInput(PaymentMethod.CASH, quote.total_due)],
        "LINE10",
    )
    session.flush()
    sale_line = next(line for line in order.lines if line.action == LineAction.BUY)
    after = service.operational_report()

    assert sum((line.discount_amount for line in order.lines), Decimal("0")) == quote.discount
    assert sale_line.discount_amount == Decimal("20000")
    assert after.rental_revenue - before.rental_revenue == Decimal("90000")
    assert after.sale_revenue - before.sale_revenue == Decimal("180000")
    assert after.gross_revenue - before.gross_revenue == Decimal("300000")
    assert after.discounts_granted - before.discounts_granted == Decimal("30000")
    assert after.average_discount_rate == after.discounts_granted * Decimal("100") / after.gross_revenue
    assert service.return_sale(sale_line.id, employee_id) == Decimal("180000")
    session.rollback()


def test_fixed_combo_applies_only_when_all_required_items_are_selected(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    second_item = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim ghép combo")
    second_copy = service.add_copy(second_item.id, "DVD-COMBO-001", actor_id=manager_id(session))
    first_copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    combo = service.create_fixed_combo("Combo cuối tuần", [item.id, second_item.id], Decimal("10000"), employee_id)

    quote = service.quote(
        customer.id,
        [
            CheckoutLine(first_copy.id, LineAction.RENT, date.today() + timedelta(days=3)),
            CheckoutLine(second_copy.id, LineAction.RENT, date.today() + timedelta(days=3)),
        ],
        combo_ids=[combo.id],
    )

    assert quote.discount_sources == {"COMBO": Decimal("10000")}
    service.checkout(
        customer.id,
        employee_id,
        
        [
            CheckoutLine(first_copy.id, LineAction.RENT, date.today() + timedelta(days=3)),
            CheckoutLine(second_copy.id, LineAction.RENT, date.today() + timedelta(days=3)),
        ],
        [PaymentInput(PaymentMethod.CASH, quote.total_due)],
        combo_ids=[combo.id],
    )
    session.flush()

    assert (combo.name, 1) in service.operational_report().top_combos
    session.rollback()


def test_show_episode_combo_applies_to_required_episodes(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    show = service.create_show("Bộ phim nhiều tập", actor_id=manager_id(session))
    episodes = service.add_episodes_bulk(show.id, 1, 1, 2, actor_id=manager_id(session))
    copies = [service.add_copy(episode.id, f"DVD-SHOW-{episode.id}", actor_id=manager_id(session)) for episode in episodes]
    employee_id = session.query(Employee.id).first()[0]
    combo = service.create_show_episode_combo("Combo 2 tập", show.id, 2, Decimal("5000"), employee_id)

    quote = service.quote(
        customer.id,
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3)) for copy in copies],
        combo_ids=[combo.id],
    )

    assert quote.discount_sources == {"COMBO": Decimal("5000")}
    session.rollback()


def test_order_detail_lists_rented_item_and_due_date(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    due_date = date.today() + timedelta(days=3)
    order = service.checkout(customer.id, employee_id,  [CheckoutLine(copy.id, LineAction.RENT, due_date)], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    session.flush()

    summary, lines = service.order_detail(order.id)

    assert summary.code == order.code
    assert lines[0].title == item.title
    assert lines[0].due_date == due_date
    session.rollback()


def test_description_search_and_today_recommendations_use_catalog(session):
    service = _StoreOperations(session)
    item = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Kỳ nghỉ mùa hè", overview="Câu chuyện gia đình vui nhộn bên bờ biển", vote_average=Decimal("8.5"))
    service.add_copy(item.id, "DVD-SEARCH-001", actor_id=manager_id(session))

    results = service.search_by_description("gia đình vui nhộn")
    recommendations = service.today_recommendations()

    assert any(result.item_id == item.id for result in results)
    assert any(result.item_id == item.id for result in recommendations)
    session.rollback()


def test_description_search_uses_cached_embedding_when_available(session, monkeypatch):
    service = _StoreOperations(session)
    first = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Bí ẩn trên núi", overview="Câu chuyện bí ẩn")
    second = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Bí ẩn dưới biển", overview="Câu chuyện bí ẩn")
    service.add_copy(first.id, "DVD-EMBED-001", actor_id=manager_id(session))
    service.add_copy(second.id, "DVD-EMBED-002", actor_id=manager_id(session))
    session.add_all([
        ContentEmbedding(item_id=first.id, model="test", dimensions=2, vector=np.array([1, 0], dtype=np.float32).tobytes(), source_hash="a"),
        ContentEmbedding(item_id=second.id, model="test", dimensions=2, vector=np.array([0, 1], dtype=np.float32).tobytes(), source_hash="b"),
    ])
    session.flush()
    monkeypatch.setattr("normastore.application.ai_search.GeminiSearch.embed", lambda _self, _text: np.array([0, 1], dtype=np.float32))

    results = search_local(SearchRepository(session), "đại dương mênh mông", "test-key")

    assert results[0].item_id == second.id
    assert results[0].source == "AI (Gemini)"
    session.rollback()


def test_manual_catalog_genres_support_filtering_and_sales_statistics(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim tự nhập thể loại",
                                     genre_names=["Hành động thử", "Chính kịch thử", "Hành động thử"])
    session.flush()
    assert set(service.catalog_metadata(item.id)[0]) == {"Hành động thử", "Chính kịch thử"}
    genre = session.query(Genre).filter_by(name="Hành động thử").one()
    service.save_catalog_item(actor, id=item.id, title="Phim tự nhập đã sửa")
    assert set(service.catalog_metadata(item.id)[0]) == {"Hành động thử", "Chính kịch thử"}
    service.save_catalog_item(actor, id=item.id, genre_names=["Hành động thử"])
    session.flush()
    assert service.catalog_metadata(item.id)[0] == ("Hành động thử",)
    assert service.query_checkout_catalog(CatalogFilters(genre_id=genre.id)).items[0].item_id == item.id
    copy = service.add_copy(item.id, "MANUAL-GENRE-001", actor_id=actor)
    customer = service.list_customers()[0]
    lines = [CheckoutLine(copy.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    assert (genre.name, 1) in service.chart_report(date.today(), date.today(), genre_id=genre.id).genres
    service.save_catalog_item(actor, id=item.id, genre_names=[])
    session.flush()
    assert service.catalog_metadata(item.id)[0] == ()
    with pytest.raises(BusinessError, match="80 ký tự"):
        service.save_catalog_item(actor, id=item.id, genre_names=["x" * 81])
    session.rollback()


def test_catalog_metadata_returns_tmdb_genres_and_reviews(session):
    service = _StoreOperations(session)
    item = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim có metadata TMDB")
    genre = Genre(name="Phiêu lưu")
    session.add(genre)
    session.flush()
    session.add(ItemGenre(item_id=item.id, genre_id=genre.id))
    session.add(ExternalReview(
        item_id=item.id,
        tmdb_review_id="tmdb-review-test-001",
        author="Khán giả TMDB",
        rating=Decimal("8.5"),
        content="Một bộ phim rất đáng xem.",
    ))
    session.flush()

    genres, reviews = service.catalog_metadata(item.id)

    assert genres == ("Phiêu lưu",)
    assert reviews[0].author == "Khán giả TMDB"
    assert reviews[0].rating == Decimal("8.5")
    session.rollback()


def test_create_employee_account_assigns_requested_role(session):
    service = _StoreOperations(session)

    actor_id = session.query(Employee.id).first()[0]
    employee = service.create_employee_account("Nguyễn Quốc Bảo", "0909999000", "bao.staff", RoleCode.STAFF, "matkhau123", actor_id)
    session.flush()

    assert any(row.employee_id == employee.id and row.role_name == "Nhân viên" for row in service.list_employees())
    session.rollback()




def test_return_records_deposit_refund_in_ledger(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    order = service.checkout(customer.id, employee_id,  [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    session.flush()
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()

    balance = service.return_rentals(employee_id, customer.id, [(term.id, ReturnOutcome.NORMAL, "")])
    session.flush()

    assert balance < 0
    assert session.query(PaymentTransaction).filter_by(customer_id=customer.id, category="DEPOSIT_REFUND", amount=balance).count() == 1
    session.rollback()


def test_overdue_return_shows_recorded_deposit_and_deducts_penalty(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Kiểm tra phạt trả trễ")
    copy = service.add_copy(item.id, "RETURN-LATE-TEST", actor_id=actor)
    due = date.today() + timedelta(days=1)
    order = service.checkout(customer.id, actor, [CheckoutLine(copy.id, LineAction.RENT, due)],
                             [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()
    rental = next(row for row in service.active_rentals() if row.term_id == term.id)
    assert rental.deposit_amount == order.lines[0].deposit_amount
    assert rental.replacement_value == item.replacement_value
    penalty = Decimal(term.late_daily_rate) * 2
    balance = service.return_rentals(actor, customer.id, [(term.id, ReturnOutcome.NORMAL, "")],
                                     today=due + timedelta(days=2))
    session.flush()
    assert balance == penalty - rental.deposit_amount
    assert session.query(PenaltyCharge).filter_by(rental_term_id=term.id, kind="LATE").one().amount == penalty
    if balance < 0:
        assert session.query(PaymentTransaction).filter_by(customer_id=customer.id, category="DEPOSIT_REFUND", amount=balance).count() >= 1
    session.rollback()


def test_partial_checkout_uses_actual_deposit_across_separate_returns(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Kiểm tra cọc thu một phần")
    copies = [service.add_copy(item.id, f"RETURN-PARTIAL-{i}", actor_id=actor) for i in (1, 2)]
    lines = [CheckoutLine(copy.id, LineAction.RENT, date.today()) for copy in copies]
    paid = Decimal("60001.01")
    quote = service.quote(customer.id, lines)
    assert paid < quote.deposit
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, paid)])
    first, second = sorted(
        (row for row in service.active_rentals() if row.order_code == order.code),
        key=lambda row: row.term_id,
    )
    assert first.order_balance_due == second.order_balance_due == quote.total_due - paid
    assert (first.deposit_paid, second.deposit_paid) == (Decimal("30000.50"), Decimal("30000.51"))

    with pytest.raises(BusinessError, match="số nguyên không âm"), session.begin_nested():
        service.return_rentals(actor, customer.id, [
            RentalReturnInput(second.term_id, ReturnOutcome.LIGHT_DAMAGE, damage_charge=Decimal("-1")),
        ])
    before = session.query(PaymentTransaction.id).order_by(PaymentTransaction.id.desc()).first()[0]
    assert service.return_rentals(actor, customer.id, [
        RentalReturnInput(second.term_id, ReturnOutcome.LIGHT_DAMAGE, damage_charge=Decimal("7000")),
    ]) == Decimal("-23000.51")
    assert service.return_rentals(actor, customer.id, [
        RentalReturnInput(first.term_id, ReturnOutcome.HEAVY_DAMAGE, damage_charge=Decimal("0")),
    ]) == Decimal("-30000.50")
    session.flush()
    penalty = session.query(PenaltyCharge).filter_by(rental_term_id=second.term_id).one()
    assert (penalty.kind, penalty.amount) == ("LIGHT_DAMAGE", Decimal("7000"))
    assert not session.query(PenaltyCharge).filter_by(rental_term_id=first.term_id).count()
    refunds = session.query(PaymentTransaction).filter(
        PaymentTransaction.id > before, PaymentTransaction.category == "DEPOSIT_REFUND",
    ).all()
    assert sum(row.amount for row in refunds) == Decimal("7000") - paid
    assert service.order_receipt(order.id).balance_due == quote.total_due - paid


def test_bulk_catalog_price_edit_updates_selected_items(session):
    service = _StoreOperations(session)
    first = service.list_catalog()[0][0]
    second = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim bulk edit")
    employee_id = session.query(Employee.id).first()[0]

    count = service.bulk_update_catalog_prices([first.id, second.id], employee_id, rental_price=Decimal("33000"))
    session.flush()

    assert count == 2
    assert service.catalog_item(first.id).rental_price == Decimal("33000")
    assert service.catalog_item(second.id).rental_price == Decimal("33000")
    session.rollback()


def test_change_password_updates_authentication(session):
    service = _StoreOperations(session)
    account = service.authenticate("admin", "admin123")
    assert account is not None

    service.change_password(account.id, "admin123", "matkhau-moi")
    session.flush()

    assert service.authenticate("admin", "matkhau-moi") is not None
    session.rollback()




def test_staff_cannot_archive_catalog_items(session):
    service = _StoreOperations(session)
    actor_id = session.query(Employee.id).first()[0]
    employee = service.create_employee_account("Trần Hải Đăng", "0909999001", "dang.staff", RoleCode.STAFF, "matkhau123", actor_id)
    item = service.list_catalog()[0][0]

    with pytest.raises(BusinessError, match="Quản lý"):
        service.archive_items([item.id], employee.id)
    session.rollback()


def test_staff_cannot_mutate_catalog_or_inventory(session):
    service = _StoreOperations(session)
    actor_id = manager_id(session)
    staff = service.create_employee_account(
        "Bui Quang Huy", "0909999012", "huy.staff", RoleCode.STAFF, "matkhau123", actor_id
    )
    item = service.save_catalog_item(actor_id, item_type="MOVIE", title="Phim cần phân quyền")

    with pytest.raises(BusinessError, match="Quản lý"):
        service.save_catalog_item(staff.id, item_type="MOVIE", title="Phim trái quyền")
    with pytest.raises(BusinessError, match="Quản lý"):
        service.save_catalog_item(staff.id, id=item.id, title="Tên sửa trái quyền")
    with pytest.raises(BusinessError, match="Quản lý"):
        service.add_copy(item.id, "DVD-STAFF-DENIED-001", actor_id=staff.id)
    with pytest.raises(BusinessError, match="Quản lý"):
        service.update_inventory_copies([1], {"rack": "A"}, staff.id)
    with pytest.raises(BusinessError, match="Quản lý"):
        service.create_show("Bộ phim trái quyền", actor_id=staff.id)
    session.rollback()




def test_staff_cannot_create_voucher(session):
    service = _StoreOperations(session)
    actor_id = session.query(Employee.id).first()[0]
    employee = service.create_employee_account("Đỗ Minh Anh", "0909999003", "anh.staff", RoleCode.STAFF, "matkhau123", actor_id)

    with pytest.raises(BusinessError, match="Quản lý"):
        service.create_voucher("STAFFONLY", employee.id, percent_off=Decimal("10"))
    session.rollback()


def test_staff_cannot_extend_overdue_rental(session):
    service = _StoreOperations(session)
    admin_id = session.query(Employee.id).first()[0]
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    order = service.checkout(
        customer.id,
        admin_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() - timedelta(days=1))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    staff = service.create_employee_account("Phạm Thu Hà", "0909999004", "ha.staff", RoleCode.STAFF, "matkhau123", admin_id)
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()

    with pytest.raises(BusinessError, match="Quản lý"):
        service.extend_rental(term.id, staff.id)
    session.rollback()


def test_extend_overdue_records_late_once_and_negotiated_fee(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Gia hạn quá hạn thử")
    copy = service.add_copy(item.id, "EXTENSION-CUSTOM-001", actor_id=actor)
    today = date.today()
    order = service.checkout(customer.id, actor, [CheckoutLine(copy.id, LineAction.RENT, today - timedelta(days=2))],
                             [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()
    service.extend_rental(term.id, actor, today + timedelta(days=3), Decimal("17000"), PaymentMethod.BANK_TRANSFER, today)
    session.flush()
    assert session.query(RentalExtension).filter_by(rental_term_id=term.id).one().fee == Decimal("17000")
    assert session.query(PenaltyCharge).filter_by(rental_term_id=term.id, kind="LATE").one().amount == Decimal("10000")
    assert session.query(PaymentTransaction).filter_by(order_id=order.id, category="EXTENSION_LATE").one().amount == Decimal("10000")
    service.return_rentals(actor, customer.id, [(term.id, ReturnOutcome.NORMAL, "")], today=today + timedelta(days=3))
    session.flush()
    assert session.query(PenaltyCharge).filter_by(rental_term_id=term.id, kind="LATE").count() == 1
    session.rollback()


def test_return_custom_condition_and_status(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Tình trạng khi trả thử")
    copy = service.add_copy(item.id, "RETURN-CONDITION-001", actor_id=actor)
    order = service.checkout(customer.id, actor, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
                             [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()
    service.return_rentals(actor, customer.id, [RentalReturnInput(term.id, ReturnOutcome.LIGHT_DAMAGE, "trầy", CopyCondition.WORN, Decimal("55"), CopyStatus.INSPECTION)])
    assert (copy.condition, copy.condition_percent, copy.status) == (CopyCondition.WORN, Decimal("55"), CopyStatus.INSPECTION)
    session.rollback()


def test_staff_cannot_extend_rental_with_waiting_reservation(session):
    service = _StoreOperations(session)
    admin_id = session.query(Employee.id).first()[0]
    customers = service.list_customers()
    customer = customers[0]
    waiting_customer = customers[1]
    item = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim chỉ còn một bản")
    copy = service.add_copy(item.id, "DVD-QUEUE-EXTEND-001", actor_id=manager_id(session))
    order = service.checkout(
        customer.id,
        admin_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    service.reserve(waiting_customer.id, [item.id])
    staff = service.create_employee_account("Nguyễn Thanh Tùng", "0909999005", "tung.staff", RoleCode.STAFF, "matkhau123", admin_id)
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()

    with pytest.raises(BusinessError, match="Quản lý"):
        service.extend_rental(term.id, staff.id)
    session.rollback()


def test_customer_recommendations_exclude_previously_rented_item(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    first = service.list_catalog()[0][0]
    first_copy = next(copy for copy in service.catalog_item(first.id).copies if copy.status == CopyStatus.AVAILABLE)
    second = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim nên đề cử", vote_average=Decimal("9"))
    service.add_copy(second.id, "DVD-RECOMMEND-001", actor_id=manager_id(session))
    employee_id = session.query(Employee.id).first()[0]
    service.checkout(customer.id, employee_id,  [CheckoutLine(first_copy.id, LineAction.BUY)], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    session.flush()

    results = service.customer_recommendations(customer.id)

    assert any(result.item_id == second.id for result in results)
    assert all(result.item_id != first.id for result in results)
    session.rollback()


def test_list_notifications_returns_customer_and_delivery_state(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    service.checkout(customer.id, employee_id,  [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    session.flush()

    notifications = service.list_notifications()

    assert any(notification.customer_name == customer.full_name and notification.channel == "EMAIL" for notification in notifications)
    session.rollback()


def test_description_search_excludes_item_without_available_copy(session):
    service = _StoreOperations(session)
    unavailable = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim bí mật", overview="Câu chuyện bí mật")
    copy = service.add_copy(unavailable.id, "DVD-UNAVAILABLE-001", actor_id=manager_id(session))
    copy.status = CopyStatus.RENTED
    available = service.save_catalog_item(manager_id(session), item_type="MOVIE", title="Phim bí mật còn hàng", overview="Câu chuyện bí mật")
    service.add_copy(available.id, "DVD-AVAILABLE-001", actor_id=manager_id(session))

    results = service.search_by_description("câu chuyện bí mật")

    assert any(result.item_id == available.id for result in results)
    assert all(result.item_id != unavailable.id for result in results)
    session.rollback()


def test_checkout_rejects_negative_payment(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]

    with pytest.raises(BusinessError, match="không được âm"):
        service.checkout(customer.id, employee_id,  [CheckoutLine(copy.id, LineAction.BUY)], [PaymentInput(PaymentMethod.CASH, Decimal("-1"))])
    session.rollback()


def test_catalog_query_counts_rent_and_sale_and_pages_globally(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    rent_only = service.save_catalog_item(actor, item_type="MOVIE", title="AAA chỉ thuê", can_sell=False)
    sale_only = service.save_catalog_item(actor, item_type="MOVIE", title="ZZZ chỉ mua", can_rent=False)
    service.add_copy(rent_only.id, "PAGE-RENT-001", actor_id=actor)
    service.add_copy(sale_only.id, "PAGE-SALE-001", actor_id=actor)
    session.flush()

    first = service.query_catalog(CatalogFilters(text="chỉ"), PageRequest(1, 1), SortSpec("title"))
    second = service.query_catalog(CatalogFilters(text="chỉ"), PageRequest(2, 1), SortSpec("title"))
    by_id = {row.item_id: row for row in (*first.items, *second.items)}

    assert first.total_items == 2
    assert first.total_pages == 2
    assert {row.item_id for row in first.items}.isdisjoint({row.item_id for row in second.items})
    assert by_id[rent_only.id].rentable_copies == 1 and by_id[rent_only.id].sellable_copies == 0
    assert by_id[sale_only.id].rentable_copies == 0 and by_id[sale_only.id].sellable_copies == 1
    assert service.query_catalog(CatalogFilters(require_sellable=True, text="chỉ mua")).items[0].item_id == sale_only.id
    assert service.query_catalog(CatalogFilters(copy_status=CopyStatus.AVAILABLE, text="chỉ thuê")).items[0].item_id == rent_only.id
    session.rollback()


def test_checkout_catalog_groups_series_before_pagination(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    show = service.create_show("GROUPCHECK series", actor_id=actor)
    episodes = service.add_episodes_bulk(show.id, 1, 1, 3, "Episode {number}", actor)
    movie = service.save_catalog_item(actor, item_type="MOVIE", title="GROUPCHECK movie")
    for number, item in enumerate((*episodes, movie)):
        service.add_copy(item.id, f"GROUPCHECK-{number}", actor_id=actor)
    session.flush()

    pages = [service.query_checkout_catalog(CatalogFilters(text="GROUPCHECK"), PageRequest(page, 1)) for page in (1, 2)]
    assert all(page.total_items == 2 and page.total_pages == 2 for page in pages)
    rows = [page.items[0] for page in pages]
    series = next(row for row in rows if row.show_id == show.id)
    assert series.title == show.title
    assert series.total_copies == series.rentable_copies == series.sellable_copies == 3
    assert any(row.item_id == movie.id and row.show_id is None for row in rows)
    assert service.query_checkout_catalog(CatalogFilters(text="GROUPCHECK series", require_sellable=True)).total_items == 1
    session.rollback()


def test_choose_checkout_copy_returns_scalar_choice_for_requested_action(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Chọn đĩa an toàn", can_sell=False)
    copy = service.add_copy(item.id, "CHOICE-RENT-001", actor_id=actor)
    session.flush()

    choice = service.choose_checkout_copy(item.id, LineAction.RENT)

    assert choice is not None
    assert choice.copy_id == copy.id
    assert choice.title == "Chọn đĩa an toàn"
    assert service.choose_checkout_copy(item.id, LineAction.BUY) is None
    assert service.choose_checkout_copy(item.id, LineAction.RENT, {copy.id}) is None
    session.rollback()


def test_checkout_copy_choices_and_inventory_search(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Kho tìm kiếm riêng")
    first = service.add_copy(item.id, "FIND-CHOICE-001", actor_id=actor)
    second = service.add_copy(item.id, "FIND-CHOICE-002", actor_id=actor)
    first.rental_price_override = Decimal("0")
    second.status = CopyStatus.REPAIR
    session.flush()

    choices = service.checkout_copies(item.id, LineAction.RENT)
    assert [(choice.copy_id, choice.unit_price) for choice in choices] == [(first.id, Decimal("0"))]
    assert service.checkout_copies(item.id, LineAction.RENT, {first.id}) == []
    assert [row.copy_id for row in service.query_inventory(text="FIND-CHOICE-002").items] == [second.id]
    assert {row.copy_id for row in service.query_inventory(text="Kho tìm kiếm riêng").items} == {first.id, second.id}
    session.rollback()


def test_rentals_have_no_limit_and_deposit_uses_sale_price(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.add_customer("Khách không giới hạn", "0987643211")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Đĩa nhiều bản", sale_price=Decimal("200000"))
    copies = [service.add_copy(item.id, f"UNLIMITED-{index}", actor_id=actor) for index in range(6)]
    copies[0].sale_price_override = Decimal("100000")
    service.save_deposit_percent(Decimal("75"), actor)
    lines = [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3)) for copy in copies]
    quote = service.quote(customer.id, lines)
    assert quote.deposit == Decimal("825000")
    order = service.checkout(customer.id, actor,  lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    assert order.deposit_total == quote.deposit
    assert sum(line.deposit_amount for line in order.lines) == quote.deposit
    session.rollback()


def test_preorder_waits_for_release_and_then_allocates_fifo(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    first = service.add_customer("Khách đặt trước một", "0987643212")
    second = service.add_customer("Khách đặt trước hai", "0987643213")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim chưa ra", release_date=date.today() + timedelta(days=1))
    copy = service.add_copy(item.id, "FUTURE-RESERVATION-01", actor_id=actor)
    listing = service.query_catalog(CatalogFilters(text="Phim chưa ra")).items[0]
    assert listing.total_copies == 1
    assert listing.rentable_copies == listing.sellable_copies == 0
    assert service.query_catalog(CatalogFilters(text="Phim chưa ra", require_rentable=True)).total_items == 0
    assert service.query_checkout_catalog(CatalogFilters(text="Phim chưa ra", require_sellable=True)).total_items == 0
    reservation = service.reserve(first.id, [item.id], actor)[0]
    service.reserve(second.id, [item.id], actor)
    session.flush()
    assert reservation.state.value == "WAITING"
    assert copy.status == CopyStatus.AVAILABLE
    assert service.checkout_copies(item.id, LineAction.RENT) == []
    with pytest.raises(BusinessError, match="chưa phát hành"):
        service.quote(first.id, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))])
    assert any(row[0] == item.id for row in service.dashboard_upcoming())
    item.release_date = date.today()
    session.flush()
    listing = service.query_catalog(CatalogFilters(text="Phim chưa ra")).items[0]
    assert listing.rentable_copies == listing.sellable_copies == 1
    assert service.allocate_released_reservations() == 1
    assert reservation.state.value == "HELD"
    assert copy.status == CopyStatus.HELD
    assert service.checkout_copies(item.id, LineAction.RENT, customer_id=second.id) == []
    assert service.checkout_copies(item.id, LineAction.RENT, customer_id=first.id)[0].copy_id == copy.id
    line = CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))
    with pytest.raises(BusinessError, match="không còn sẵn sàng"):
        service.quote(second.id, [line])
    quote = service.quote(first.id, [line])
    service.checkout(first.id, actor,  [line], [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    assert reservation.state.value == "FULFILLED"
    assert copy.status == CopyStatus.RENTED
    session.rollback()


def test_future_series_episodes_do_not_show_available_copies(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    show = service.create_show("Bộ phim chưa ra", actor_id=actor)
    episode = service.add_episodes_bulk(show.id, 1, 1, 1, actor_id=actor)[0]
    episode.release_date = date.today() + timedelta(days=1)
    service.add_copy(episode.id, "FUTURE-EPISODE", actor_id=actor)
    session.flush()
    row = service.list_show_episodes(show.id)[0]
    assert row.rentable_copies == row.sellable_copies == 0
    episode.release_date = date.today()
    session.flush()
    row = service.list_show_episodes(show.id)[0]
    assert row.rentable_copies == row.sellable_copies == 1
    session.rollback()


def test_dashboard_stock_and_popularity_queries(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Kiểm tra tồn tổng quan")
    service.add_copy(item.id, "DASHBOARD-LOW-01", actor_id=actor)
    session.flush()
    stock = {row[0]: row for row in service.dashboard_low_stock()}
    assert stock[item.id][2:] == (1, 1)
    assert isinstance(service.dashboard_popular(LineAction.RENT), list)
    assert isinstance(service.dashboard()["cash_flow"], Decimal)
    session.rollback()


def test_copy_price_modes_flow_through_selection_quote_and_deposit(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.add_customer("Khách thử giá", "0987643214")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim thử tỷ lệ", rental_price=Decimal("20000"), sale_price=Decimal("200000"), rental_price_mode="CONDITION", sale_price_mode="PERCENT", sale_price_percent=Decimal("80"))
    copy = service.add_copy(item.id, "PRICING-MODES-01", actor_id=actor)
    request = UpdateInventoryCopyRequest(copy.barcode, "DVD", CopyCondition.WORN, True, True, CopyStatus.AVAILABLE, condition_percent=Decimal("70"))
    service.update_inventory_copy(copy.id, request, actor)
    service.save_deposit_percent(Decimal("75"), actor)
    session.flush()
    assert service.checkout_copies(item.id, LineAction.RENT)[0].unit_price == Decimal("14000")
    assert service.checkout_copies(item.id, LineAction.BUY)[0].unit_price == Decimal("160000")
    line = CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))
    quote = service.quote(customer.id, [line])
    assert quote.line_prices[copy.id] == Decimal("14000")
    assert quote.line_deposits[copy.id] == Decimal("120000")
    request = UpdateInventoryCopyRequest(copy.barcode, "DVD", CopyCondition.WORN, True, True, CopyStatus.AVAILABLE, rental_price_override=Decimal("0"), condition_percent=Decimal("70"), rental_price_mode="DIRECT", sale_price_mode="PERCENT", sale_price_percent=Decimal("50"))
    service.update_inventory_copy(copy.id, request, actor)
    quote = service.quote(customer.id, [line])
    assert quote.line_prices[copy.id] == 0
    assert quote.line_deposits[copy.id] == Decimal("75000")
    session.rollback()


def test_normal_rental_return_preserves_condition_and_condition_based_price(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Giữ tình trạng khi trả",
                                     rental_price=Decimal("100000"), rental_price_mode="CONDITION")
    copy = service.add_copy(item.id, "CONDITION-RETURN-001", actor_id=actor)
    service.update_inventory_copy(copy.id, UpdateInventoryCopyRequest(
        copy.barcode, "DVD", CopyCondition.WORN, True, True, CopyStatus.AVAILABLE,
        condition_percent=Decimal("65"),
    ), actor)
    lines = [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))]
    quote = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    term = session.query(RentalTerm).filter(RentalTerm.line.has(order_id=order.id)).one()
    service.return_rentals(actor, customer.id, [(term.id, ReturnOutcome.NORMAL, "")])
    session.flush()
    assert copy.condition == CopyCondition.WORN and copy.condition_percent == Decimal("65")
    assert service.checkout_copies(item.id, LineAction.RENT)[0].unit_price == Decimal("65000")
    session.rollback()


def test_approving_returned_sale_keeps_recorded_condition(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Giữ tình trạng hàng hoàn")
    copy = service.add_copy(item.id, "CONDITION-SALE-RETURN", actor_id=actor)
    service.update_inventory_copy(copy.id, UpdateInventoryCopyRequest(
        copy.barcode, "DVD", CopyCondition.WORN, True, True, CopyStatus.AVAILABLE,
        condition_percent=Decimal("65"),
    ), actor)
    lines = [CheckoutLine(copy.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    service.return_sale(order.lines[0].id, actor, condition=CopyCondition.WORN)
    service.inspect_copy(copy.id, actor, CopyStatus.AVAILABLE)
    assert copy.condition == CopyCondition.WORN and copy.condition_percent == Decimal("65")
    session.rollback()


def test_damaged_returns_reduce_condition_based_price(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Giá sau khi đĩa hỏng",
                                     rental_price=Decimal("100000"), sale_price=Decimal("200000"),
                                     rental_price_mode="CONDITION", sale_price_mode="CONDITION")
    sold = service.add_copy(item.id, "CONDITION-WORN-RETURN", actor_id=actor)
    rented = service.add_copy(item.id, "CONDITION-DAMAGED-RETURN", actor_id=actor)
    lines = [CheckoutLine(sold.id, LineAction.BUY),
             CheckoutLine(rented.id, LineAction.RENT, date.today() + timedelta(days=3))]
    quote = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    sale_line = next(line for line in order.lines if line.copy_id == sold.id)
    term = session.query(RentalTerm).filter(RentalTerm.line.has(order_id=order.id, copy_id=rented.id)).one()
    service.return_sale(sale_line.id, actor, condition=CopyCondition.WORN)
    service.inspect_copy(sold.id, actor, CopyStatus.AVAILABLE)
    assert sold.condition_percent == Decimal("70")
    assert service.checkout_copies(item.id, LineAction.BUY)[0].unit_price == Decimal("140000")
    service.return_rentals(actor, customer.id, [(term.id, ReturnOutcome.LIGHT_DAMAGE, "")])
    assert rented.condition == CopyCondition.DAMAGED
    assert rented.condition_percent == Decimal("0")
    session.rollback()


def test_season_choices_allow_missing_episodes_and_selecting_copy(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.add_customer("Khách chọn tập", "0987643215")
    show = service.create_show("Bộ phim chọn tập", actor_id=actor)
    episodes = service.add_episodes_bulk(show.id, 1, 1, 3, actor_id=actor)
    copies = [service.add_copy(episode.id, f"SEASON-SELECT-{number}", actor_id=actor) for number, episode in enumerate(episodes, 1)]
    session.flush()
    result = service.season_checkout_choices(show.id, 1, LineAction.RENT, customer.id, first_episode=2, last_episode=3)
    assert [episode.episode_number for episode, _ in result] == [2, 3]
    assert [choices[0].copy_id for _, choices in result] == [copies[1].id, copies[2].id]
    partial = service.season_checkout_choices(show.id, 1, LineAction.RENT, customer.id, {copies[1].id})
    assert [episode.episode_number for episode, choices in partial if not choices] == [2]
    partial = service.season_checkout_choices(show.id, 1, LineAction.BUY, customer.id, first_episode=2, last_episode=4)
    assert [episode.episode_number for episode, _ in partial] == [2, 3]
    line = CheckoutLine(copies[0].id, LineAction.RENT, date.today() + timedelta(days=3))
    with pytest.raises(BusinessError, match="không thể xuất hiện nhiều lần"):
        service.quote(customer.id, [line, line])
    session.rollback()


def test_inventory_location_saved_and_filters_nested_groups(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    show = service.create_show("Bộ kiểm tra vị trí", actor_id=actor)
    episode = service.add_episodes_bulk(show.id, 1, 1, 1, actor_id=actor)[0]
    copy = service.add_copy(episode.id, "LOCATION-TEST-001", actor_id=actor,
                            aisle="A1", rack="K2", compartment="N3")
    session.flush()
    location = ("a1", "K2", "N3")
    rows = service.query_inventory(text="LOCATION-TEST-001", location=location)
    assert len(rows.items) == 1
    assert (rows.items[0].aisle, rows.items[0].rack, rows.items[0].compartment) == ("A1", "K2", "N3")
    assert service.inventory_groups(None, "", None, "", False, False, PageRequest(), location=location).items
    assert service.inventory_group_episodes(show.id, None, "", None, "", False, False, location=location)[0].item_id == episode.id
    assert not service.query_inventory(text="LOCATION-TEST-001", location=("A1", "wrong", "")).items
    choice = service.checkout_copies(episode.id, LineAction.RENT)[0]
    assert choice.copy_id == copy.id and choice.compartment == "N3"
    session.rollback()


def test_catalog_cover_paths_and_episode_fallback(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    show = service.create_show("Bộ có ảnh bìa", actor_id=actor)
    episode = service.add_episodes_bulk(show.id, 1, 1, 1, actor_id=actor)[0]
    service.set_show_poster(show.id, "https://example.test/show.jpg", actor)
    session.flush()
    row = service.query_catalog(CatalogFilters(text=episode.title)).items
    assert next(item for item in row if item.item_id == episode.id).poster_path == "https://example.test/show.jpg"
    service.save_catalog_item(actor, id=episode.id, poster_path="C:/posters/episode.png")
    session.flush()
    row = service.query_catalog(CatalogFilters(text=episode.title)).items
    assert next(item for item in row if item.item_id == episode.id).poster_path == "C:/posters/episode.png"
    service.save_catalog_item(actor, id=episode.id, poster_path=None)
    session.flush()
    row = service.query_catalog(CatalogFilters(text=episode.title)).items
    assert next(item for item in row if item.item_id == episode.id).poster_path == "https://example.test/show.jpg"
    session.rollback()


def test_chart_report_filters_revenue_damage_and_genres(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.add_customer("Khách biểu đồ", "0987643216")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim thống kê riêng", rental_price=Decimal("20000"), sale_price=Decimal("100000"))
    genre = Genre(name="Thể loại thống kê riêng")
    second_genre = Genre(name="Thể loại thống kê phụ")
    session.add_all([genre, second_genre])
    session.flush()
    session.add_all([ItemGenre(item_id=item.id, genre_id=genre.id), ItemGenre(item_id=item.id, genre_id=second_genre.id)])
    rent_copy = service.add_copy(item.id, "CHART-RENT-01", actor_id=actor)
    sale_copy = service.add_copy(item.id, "CHART-SALE-01", actor_id=actor)
    lines = [CheckoutLine(rent_copy.id, LineAction.RENT, date.today() + timedelta(days=3)), CheckoutLine(sale_copy.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor,  lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    term = session.query(RentalTerm).filter(RentalTerm.line.has(order_id=order.id, copy_id=rent_copy.id)).one()
    service.return_rentals(actor, customer.id, [(term.id, ReturnOutcome.LIGHT_DAMAGE, "")])
    session.flush()
    report = service.chart_report(date.today(), date.today(), None, genre.id)
    assert {(action, amount) for _, action, amount in report.revenue} == {(LineAction.RENT, Decimal("20000")), (LineAction.BUY, Decimal("100000"))}
    assert report.damages == (("LIGHT_DAMAGE", 1),)
    assert report.genres == ((genre.name, 1),)
    report_buy = service.chart_report(date.today(), date.today(), LineAction.BUY, genre.id)
    assert report_buy.damages == ()
    assert all(action == LineAction.BUY for _, action, _ in report_buy.revenue)
    assert service.chart_report(date.today(), date.today(), LineAction.RENT, genre.id).genres == ()
    sale_line = session.query(OrderLine).filter_by(order_id=order.id, copy_id=sale_copy.id).one()
    service.return_sale(sale_line.id, actor, condition=CopyCondition.DAMAGED)
    service.inspect_copy(sale_copy.id, actor, CopyStatus.AVAILABLE)
    session.flush()
    assert service.chart_report(date.today(), date.today(), LineAction.BUY, genre.id).damages == (("SALE_DAMAGED", 1),)
    assert set(service.chart_report(date.today(), date.today(), None, genre.id).damages) == {("LIGHT_DAMAGE", 1), ("SALE_DAMAGED", 1)}
    assert service.chart_report(date.today(), date.today(), LineAction.RENT, genre.id).damages == (("LIGHT_DAMAGE", 1),)
    session.rollback()


def test_reports_use_vietnamese_business_day_for_utc_transactions(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim giao dịch gần nửa đêm", sale_price=Decimal("123000"))
    genre = Genre(name="Thể loại giao dịch gần nửa đêm")
    session.add(genre)
    session.flush()
    session.add(ItemGenre(item_id=item.id, genre_id=genre.id))
    copy = service.add_copy(item.id, "BUSINESS-DAY-001", actor_id=actor)
    lines = [CheckoutLine(copy.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    order.created_at = datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc)
    payment = session.query(PaymentTransaction).filter_by(order_id=order.id).one()
    payment.created_at = order.created_at
    session.flush()

    local_day = date(2026, 1, 2)
    assert service.chart_report(local_day, local_day, genre_id=genre.id).revenue == ((local_day, LineAction.BUY, Decimal("123000")),)
    report = service.operational_report(local_day, local_day)
    assert report.sale_revenue == Decimal("123000")
    assert report.cash_collected == Decimal("123000")
    assert service.chart_report(date(2026, 1, 1), date(2026, 1, 1), genre_id=genre.id).revenue == ()
    session.rollback()


def test_sale_return_deadline_uses_vietnamese_sale_date(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim bán gần nửa đêm")
    copy = service.add_copy(item.id, "SALE-LOCAL-DATE", actor_id=actor)
    lines = [CheckoutLine(copy.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    order.created_at = datetime(2026, 1, 1, 18, 0, tzinfo=timezone.utc)
    session.flush()
    local_sale_date = date(2026, 1, 2)
    deadline = date(2026, 1, 9)
    sale = next(row for row in service.returnable_sales(deadline) if row.line_id == order.lines[0].id)
    assert sale.sold_on == local_sale_date and sale.expires_on == deadline
    assert service.return_sale(sale.line_id, actor, today=deadline) == quote.total_due
    session.rollback()


def test_dashboard_stock_and_upcoming_are_paginated_and_actionable(session):
    service = _StoreOperations(session)
    stock = [CatalogItem(item_type="MOVIE", title=f"DASH-STOCK-{index:03}") for index in range(105)]
    future = [CatalogItem(item_type="MOVIE", title=f"DASH-FUTURE-{index:03}",
                          release_date=date.today() + timedelta(days=1)) for index in range(105)]
    disabled = CatalogItem(item_type="MOVIE", title="DASH-FUTURE-DISABLED", can_rent=False, can_sell=False,
                           release_date=date.today() + timedelta(days=1))
    session.add_all([*stock, *future, disabled])
    session.flush()
    stock_pages = [service.query_dashboard_low_stock(PageRequest(page, 50)) for page in range(1, 4)]
    stock_rows = [row for result in stock_pages for row in result.items]
    assert sum(row[1].startswith("DASH-STOCK-") for row in stock_rows) == 105
    assert all(not row[1].startswith("DASH-FUTURE-") for row in stock_rows)
    assert all(row[2] == 0 and row[3] == 0 for row in stock_pages[0].items)
    upcoming_pages = [service.query_dashboard_upcoming(PageRequest(page, 50)) for page in range(1, 4)]
    upcoming_rows = [row for result in upcoming_pages for row in result.items]
    assert sum(row[1].startswith("DASH-FUTURE-") for row in upcoming_rows) == 105
    assert all(row[1] != "DASH-FUTURE-DISABLED" for row in upcoming_rows)
    session.rollback()


def test_inventory_groups_search_pagination_and_matching_children(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    show = service.create_show("Bộ kho phân cấp", actor_id=actor)
    episodes = service.add_episodes_bulk(show.id, 1, 1, 2, actor_id=actor)
    first = service.add_copy(episodes[0].id, "GROUP-ONLY-0001", actor_id=actor)
    second = service.add_copy(episodes[1].id, "GROUP-ONLY-0002", actor_id=actor)
    second.status = CopyStatus.REPAIR
    session.flush()
    args = (None, "GROUP-ONLY-0001", None, "", False, False)
    groups = service.inventory_groups(*args, PageRequest(1, 50))
    assert len(groups.items) == 1
    assert groups.items[0].is_show and groups.items[0].group_id == show.id
    children = service.inventory_group_episodes(show.id, *args)
    assert [row.item_id for row in children] == [episodes[0].id]
    copies = service.query_inventory(None, PageRequest(1, 50), SortSpec("barcode"), "GROUP-ONLY-0001", episodes[0].id)
    assert [row.copy_id for row in copies.items] == [first.id]
    args = (CopyStatus.REPAIR, "Bộ kho phân cấp", None, "", False, False)
    assert [row.item_id for row in service.inventory_group_episodes(show.id, *args)] == [episodes[1].id]
    assert service.inventory_groups(*args, PageRequest(1, 1)).total_items == 1
    args = (None, "Bộ kho phân cấp", None, "", False, False)
    assert [row.item_id for row in service.inventory_group_episodes(show.id, *args, item_id=episodes[1].id)] == [episodes[1].id]
    assert service.inventory_groups(*args, PageRequest(1, 1), item_id=episodes[1].id).items[0].group_id == show.id
    session.rollback()


def test_reservation_allocates_only_usable_new_copies_and_supports_sale_only(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Đặt trước chỉ thuê", can_sell=False)
    wrong = service.add_copy(item.id, "RESERVE-WRONG-RIGHTS", actor_id=actor, can_rent=False, can_sell=True)
    reservation = service.reserve(customer.id, [item.id], actor)[0]
    assert reservation.state.value == "WAITING"
    assert wrong.status == CopyStatus.AVAILABLE
    suitable = service.add_copy(item.id, "RESERVE-USABLE", actor_id=actor, can_rent=True, can_sell=False)
    assert reservation.state.value == "HELD"
    assert reservation.allocated_copy_id == suitable.id
    assert suitable.status == CopyStatus.HELD

    future = service.save_catalog_item(actor, item_type="MOVIE", title="Đặt trước chỉ mua", can_rent=False,
                                       release_date=date.today() + timedelta(days=1))
    assert service.query_catalog(CatalogFilters(text="Đặt trước chỉ mua", item_rentable_or_sellable=True)).items[0].item_id == future.id
    sale_reservation = service.reserve(customer.id, [future.id], actor)[0]
    sale_copy = service.add_copy(future.id, "RESERVE-FUTURE-SALE", actor_id=actor)
    assert sale_reservation.state.value == "WAITING" and sale_copy.status == CopyStatus.AVAILABLE
    future.release_date = date.today()
    session.flush()
    service.allocate_waiting_reservations(future.id)
    assert sale_reservation.state.value == "HELD" and sale_reservation.allocated_copy_id == sale_copy.id
    assert service.checkout_copies(future.id, LineAction.BUY, customer_id=customer.id)[0].copy_id == sale_copy.id
    session.rollback()


@pytest.mark.parametrize("status", [CopyStatus.RENTED, CopyStatus.HELD, CopyStatus.SOLD])
def test_inventory_can_update_prices_without_changing_transaction_status(session, status):
    service = _StoreOperations(session)
    actor = manager_id(session)
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim sửa giá theo đĩa")
    copy = service.add_copy(item.id, f"EDIT-TRANSACTION-{status.value}", actor_id=actor)
    copy.status = status
    session.flush()
    request = UpdateInventoryCopyRequest(copy.barcode, "DVD", CopyCondition.GOOD, True, True, status,
                                         sale_price_override=Decimal("135000"), sale_price_mode="DIRECT")
    updated = service.update_inventory_copy(copy.id, request, actor)
    assert updated.status == status
    assert updated.sale_price_override == Decimal("135000")
    change_status = UpdateInventoryCopyRequest(copy.barcode, "DVD", CopyCondition.GOOD, True, True,
                                               CopyStatus.AVAILABLE, note="Không được đổi tay")
    with pytest.raises(BusinessError, match="Không thể ép đổi trạng thái"):
        service.update_inventory_copy(copy.id, change_status, actor)
    session.rollback()


def test_order_receipt_keeps_barcode_and_prices_after_inventory_edit(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.list_customers()[0]
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim giữ lịch sử", sale_price=Decimal("100000"))
    copy = service.add_copy(item.id, "HISTORY-ORIGINAL", actor_id=actor)
    lines = [CheckoutLine(copy.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    request = UpdateInventoryCopyRequest("HISTORY-NEW", "DVD", CopyCondition.GOOD, True, True,
                                         CopyStatus.SOLD, sale_price_override=Decimal("200000"), sale_price_mode="DIRECT")
    with pytest.raises(BusinessError, match="không được thay đổi"):
        service.update_inventory_copy(copy.id, request, actor)
    service.update_inventory_copy(copy.id, replace(request, barcode=copy.barcode), actor)
    # Historical snapshots also survive changes made outside the application.
    copy.barcode = "HISTORY-NEW"
    session.flush()
    receipt = service.order_receipt(order.id)
    assert receipt.lines[0].barcode == "HISTORY-ORIGINAL"
    assert receipt.lines[0].unit_price == Decimal("100000")
    assert service.order_detail(order.id)[1][0].barcode == "HISTORY-ORIGINAL"
    session.rollback()


def test_discovery_discount_applies_only_to_selected_title_and_respects_cap(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.add_customer("Khách ưu đãi khám phá", "0987643217")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Khám phá ưu đãi", sale_price=Decimal("100000"))
    other = service.save_catalog_item(actor, item_type="MOVIE", title="Không có ưu đãi", sale_price=Decimal("100000"))
    first = service.add_copy(item.id, "DISCOVERY-001", actor_id=actor)
    second = service.add_copy(other.id, "DISCOVERY-002", actor_id=actor)
    service.set_discovery_discount(item.id, Decimal("20"), True, date.today(), date.today(), actor)
    lines = [CheckoutLine(first.id, LineAction.BUY), CheckoutLine(second.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    assert quote.discount_sources["DISCOVERY"] == Decimal("20000")
    assert quote.line_discounts == {first.id: Decimal("20000"), second.id: Decimal("0")}
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)])
    session.flush()
    assert {line.copy_id: line.discount_amount for line in order.lines} == quote.line_discounts
    assert session.query(OrderDiscount).filter_by(order_id=order.id, source="DISCOVERY").one().amount == Decimal("20000")
    service.set_discovery_discount(other.id, Decimal("100"), True, None, None, actor)
    third = service.add_copy(item.id, "DISCOVERY-003", actor_id=actor)
    fourth = service.add_copy(other.id, "DISCOVERY-004", actor_id=actor)
    quote = service.quote(customer.id, [CheckoutLine(third.id, LineAction.BUY), CheckoutLine(fourth.id, LineAction.BUY)])
    assert quote.discount == Decimal("100000")
    assert sum(quote.line_discounts.values()) == quote.discount
    assert all(quote.line_discounts[copy_id] <= price for copy_id, price in quote.line_prices.items())
    session.rollback()


def test_discovery_and_random_exclude_unavailable_and_future(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Khám phá chưa có lượt")
    future = service.save_catalog_item(actor, item_type="MOVIE", title="Khám phá chưa phát hành", release_date=date.today() + timedelta(days=1))
    service.add_copy(item.id, "DISCOVERY-AVAILABLE", actor_id=actor)
    service.add_copy(future.id, "DISCOVERY-FUTURE", actor_id=actor)
    session.flush()
    rows = service.dashboard_discovery()
    assert any(row[0] == item.id and row[2] == 0 for row in rows)
    assert all(row[0] != future.id for row in rows)
    assert all(row[0] != future.id for row in service.dashboard_random())
    session.rollback()


def test_checkout_rejects_changed_quote_and_does_not_consume_copy(session):
    service = _StoreOperations(session)
    actor = manager_id(session)
    customer = service.add_customer("Khách đổi giá", "0987643218")
    item = service.save_catalog_item(actor, item_type="MOVIE", title="Phim đổi giá", sale_price=Decimal("100000"))
    copy = service.add_copy(item.id, "CHANGED-QUOTE-01", actor_id=actor)
    lines = [CheckoutLine(copy.id, LineAction.BUY)]
    quote = service.quote(customer.id, lines)
    item.sale_price = Decimal("200000")
    session.flush()
    with pytest.raises(BusinessError, match="đã thay đổi"):
        service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, quote.total_due)], expected_quote=quote)
    assert copy.status == CopyStatus.AVAILABLE
    updated = service.quote(customer.id, lines)
    order = service.checkout(customer.id, actor, lines, [PaymentInput(PaymentMethod.CASH, updated.total_due)], expected_quote=updated)
    assert order.gross_total == Decimal("200000")
    session.rollback()


def test_customer_contact_preferences_and_premium_expiry(session):
    service = _StoreOperations(session)
    customer = service.add_customer("Khách đầy đủ", "0987643219", "khach@example.test", address="123 Đường Mẫu", email_opt_in=False, sms_opt_in=True)
    assert customer.email == "khach@example.test"
    assert customer.address == "123 Đường Mẫu"
    assert not customer.email_opt_in and customer.sms_opt_in
    assert service.premium_until(customer.id) is None
    service.activate_premium(customer.id, 30)
    assert service.premium_until(customer.id) == date.today() + timedelta(days=29)
    session.rollback()
