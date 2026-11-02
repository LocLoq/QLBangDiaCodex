from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import numpy as np
import pytest

from normastore.application.ai_search import search_local
from normastore.application.contracts import BusinessError, CatalogFilters, CheckoutLine, PageRequest, PaymentInput, SortSpec
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
    ContentEmbedding,
    Employee,
    ExternalReview,
    Genre,
    ItemGenre,
    NotificationOutbox,
    OrderDiscount,
    PaymentTransaction,
    PremiumMembership,
    RentalTerm,
    ReputationEvent,
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


def test_active_rentals_lists_checked_out_copy(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status.value == "AVAILABLE")
    employee_id = session.query(Employee.id).first()[0]
    service.checkout(
        customer.id,
        employee_id,
        None,
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
        None,
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
        None,
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    session.flush()
    term = session.query(RentalTerm).filter_by(line_id=session.query(RentalTerm.line_id).order_by(RentalTerm.id.desc()).first()[0]).first()

    sale = service.rental_to_sale(term.id, employee_id, PaymentInput(PaymentMethod.CASH, Decimal("0")))
    session.flush()

    assert term.state.value == "PURCHASED"
    assert copy.status.value == "SOLD"
    assert sale.discount_total == term.line.deposit_amount
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
        None,
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
        None,
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
        None,
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
        None,
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
        None,
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
        None,
        [CheckoutLine(copy.id, LineAction.BUY)],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    service.checkout(
        customers[0].id,
        employee_id,
        None,
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
        None,
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
        None,
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
        None,
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
        None,
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
    order = service.checkout(customer.id, employee_id, None, [CheckoutLine(copy.id, LineAction.RENT, due_date)], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
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


def test_manual_reputation_adjustment_is_clamped_and_audited(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    employee_id = session.query(Employee.id).first()[0]
    customer.reputation_score = 98

    service.adjust_reputation(customer.id, 10, "Khách trả đúng hạn liên tục", employee_id)
    session.flush()

    assert customer.reputation_score == 100
    assert session.query(ReputationEvent).filter_by(customer_id=customer.id, delta=2).count() == 1
    session.rollback()


def test_return_records_deposit_refund_in_ledger(session):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.query(Employee.id).first()[0]
    order = service.checkout(customer.id, employee_id, None, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
    session.flush()
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()

    balance = service.return_rentals(employee_id, customer.id, [(term.id, ReturnOutcome.NORMAL, "")])
    session.flush()

    assert balance < 0
    assert session.query(PaymentTransaction).filter_by(customer_id=customer.id, category="DEPOSIT_REFUND", amount=balance).count() == 1
    session.rollback()


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


def test_only_owner_or_manager_can_close_shift(session):
    service = _StoreOperations(session)
    actor_id = manager_id(session)
    owner = service.create_employee_account(
        "Vo Minh Tuan", "0909999013", "tuan.staff", RoleCode.STAFF, "matkhau123", actor_id
    )
    other = service.create_employee_account(
        "Ngo Hai Yen", "0909999014", "yen.staff", RoleCode.STAFF, "matkhau123", actor_id
    )

    with pytest.raises(BusinessError, match="không được âm"):
        service.open_shift(owner.id, Decimal("-1"))
    shift = service.open_shift(owner.id, Decimal("100000"))
    with pytest.raises(BusinessError, match="Quản lý"):
        service.close_shift(shift.id, Decimal("100000"), other.id)

    closed = service.close_shift(shift.id, Decimal("110000"), actor_id)

    assert closed.closed_at is not None
    assert closed.closing_cash == Decimal("110000")
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
        service.create_show("Bộ phim trái quyền", actor_id=staff.id)
    session.rollback()


def test_staff_cannot_adjust_customer_reputation(session):
    service = _StoreOperations(session)
    actor_id = session.query(Employee.id).first()[0]
    employee = service.create_employee_account("Lê Hoài Nam", "0909999002", "nam.staff", RoleCode.STAFF, "matkhau123", actor_id)
    customer = service.list_customers()[0]

    with pytest.raises(BusinessError, match="Quản lý"):
        service.adjust_reputation(customer.id, 1, "Không có quyền", employee.id)
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
        None,
        [CheckoutLine(copy.id, LineAction.RENT, date.today() - timedelta(days=1))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    staff = service.create_employee_account("Phạm Thu Hà", "0909999004", "ha.staff", RoleCode.STAFF, "matkhau123", admin_id)
    term = session.query(RentalTerm).filter_by(line_id=order.lines[0].id).one()

    with pytest.raises(BusinessError, match="Quản lý"):
        service.extend_rental(term.id, staff.id)
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
        None,
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
    service.checkout(customer.id, employee_id, None, [CheckoutLine(first_copy.id, LineAction.BUY)], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
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
    service.checkout(customer.id, employee_id, None, [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))], [PaymentInput(PaymentMethod.CASH, Decimal("500000"))])
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
        service.checkout(customer.id, employee_id, None, [CheckoutLine(copy.id, LineAction.BUY)], [PaymentInput(PaymentMethod.CASH, Decimal("-1"))])
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
