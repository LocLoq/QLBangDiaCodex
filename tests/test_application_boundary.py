from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from functools import partial
from threading import Barrier, Event
from types import SimpleNamespace

import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import sessionmaker

from normastore.application.contracts import (
    AccountView,
    BusinessError,
    CatalogItemView,
    CheckoutLine,
    CustomerView,
    PaymentInput,
    PageRequest,
)
from normastore.application.services import StoreService
from normastore.domain.enums import (
    CopyStatus,
    ItemType,
    LineAction,
    PaymentMethod,
    RentalState,
    ReturnOutcome,
    RoleCode,
)
from normastore.infrastructure.database.models import (
    AuditLog,
    CatalogItem,
    Customer,
    OrderLine,
    PaymentTransaction,
    PhysicalCopy,
    PremiumMembership,
    RentalTerm,
    Reservation,
    ReturnReceipt,
)
from normastore.infrastructure.database.unit_of_work import UnitOfWork
from normastore.ui.shell import ShellMixin


@pytest.fixture
def store(session):
    factory = sessionmaker(
        bind=session.connection(), expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    settings = SimpleNamespace(
        gemini_embedding_model="gemini-embedding-001",
        gemini_embedding_dimensions=768,
        gemini_generation_model="gemini-3.5-flash-lite",
    )
    integrations = SimpleNamespace(settings=settings, gemini_api_key=lambda: None, gemini_factory=lambda *args: None)
    return StoreService(partial(UnitOfWork, factory), integrations)


def test_service_returns_customer_view_after_session_close_and_rolls_back_errors(store):
    customer = store.add_customer("Khách kiểm thử", "0987123987")
    assert isinstance(customer, CustomerView)
    assert customer.full_name == "Khách kiểm thử"
    assert not hasattr(customer, "_sa_instance_state")
    with pytest.raises(BusinessError, match="đã tồn tại"):
        store.add_customer("Trùng số", "0987123987")
    assert store.list_customers("0987123987")[0] == customer


def test_customer_page_includes_premium_state_and_paginated_views(store, session):
    customers = [store.add_customer(f"Khách phân trang {index}", f"09876655{index:02d}") for index in range(3)]
    store.activate_premium(customers[1].id, 30)
    queries = []
    def record_query(_conn, _cursor, statement, _parameters, _context, _executemany):
        if statement.lstrip().upper().startswith("SELECT"):
            queries.append(statement)
    connection = session.connection()
    event.listen(connection, "before_cursor_execute", record_query)
    try:
        first = store.query_customers_with_premium("Khách phân trang", PageRequest(1, 2))
    finally:
        event.remove(connection, "before_cursor_execute", record_query)
    second = store.query_customers_with_premium("Khách phân trang", PageRequest(2, 2))
    assert len(queries) == 2
    assert first.total_items == 3 and first.total_pages == 2
    rows = (*first.items, *second.items)
    assert all(isinstance(customer, CustomerView) for customer, _ in rows)
    assert {customer.id for customer, active in rows if active} == {customers[1].id}


def test_customer_edit_updates_existing_profile_and_refreshes_customer_queries(store, session):
    actor = store.authenticate("admin", "admin123").employee_id
    customer = store.add_customer("Khách kiểm tra sửa", "0987123101", "old@example.test")
    another = store.add_customer("Khách khác", "0987123102")
    store.activate_premium(customer.id, 30, actor)
    assert store.query_customers_with_premium(customer.phone).items == ((customer, True),)
    assert store.list_customers(customer.phone) == [customer]

    changes = dict(full_name=" Khách đã sửa ", email="", address=" Địa chỉ mới ",
                   email_opt_in=False, sms_opt_in=True)
    with pytest.raises(BusinessError, match="Số điện thoại đã tồn tại"):
        store.update_customer(customer.id, phone=another.phone, actor_id=actor, **changes)
    assert store.list_customers(customer.phone) == [customer]

    updated = store.update_customer(customer.id, phone=customer.phone, actor_id=actor, **changes)
    assert updated == CustomerView(
        customer.id, "Khách đã sửa", customer.phone, None, "Địa chỉ mới", False, True,
    )
    assert store.query_customers_with_premium(customer.phone).items == ((updated, True),)
    assert store.list_customers(customer.phone) == [updated]
    assert session.scalar(select(AuditLog).where(
        AuditLog.entity_id == str(customer.id), AuditLog.action == "UPDATE_CUSTOMER",
    )).actor_id == actor


def test_edit_and_cancel_premium_preserve_memberships_and_payments(store, session):
    actor = store.authenticate("admin", "admin123").employee_id
    customer = store.add_customer("Khách chỉnh Premium", "0987123103")
    store.activate_premium(customer.id, 30, actor)
    store.activate_premium(customer.id, 90, actor)
    today = date.today()
    assert store.premium_until(customer.id) == today + timedelta(days=89)
    with pytest.raises(BusinessError, match="trước hôm nay"):
        store.set_premium_end_date(customer.id, today - timedelta(days=1), actor)

    new_end = today + timedelta(days=17)
    store.set_premium_end_date(customer.id, new_end, actor)
    assert store.premium_until(customer.id) == new_end
    assert store.premium_active(customer.id, new_end)
    assert not store.premium_active(customer.id, new_end + timedelta(days=1))

    store.cancel_premium(customer.id, actor)
    assert store.premium_until(customer.id) is None
    assert store.query_customers_with_premium(customer.phone).items == ((customer, False),)
    rows = session.scalars(select(PremiumMembership).filter_by(customer_id=customer.id)).all()
    assert len(rows) == 2
    assert all(row.cancelled_on == today and row.ends_on == new_end for row in rows)
    payments = session.scalars(select(PaymentTransaction).filter_by(customer_id=customer.id)).all()
    assert sorted(payment.amount for payment in payments) == [Decimal("59000"), Decimal("159000")]


def test_delete_customer_keeps_history_and_removes_unused_profile(store):
    actor = store.authenticate("admin", "admin123").employee_id
    protected = store.add_customer("Khách có lịch sử Premium", "0987123104")
    empty = store.add_customer("Khách chưa giao dịch", "0987123105")
    store.activate_premium(protected.id, 30, actor)
    store.cancel_premium(protected.id, actor)
    assert store.list_customers(empty.phone) == [empty]

    with pytest.raises(BusinessError, match="đã có lịch sử"):
        store.delete_customer(protected.id, actor)
    assert store.list_customers(protected.phone) == [protected]
    store.delete_customer(empty.id, actor)
    assert store.list_customers(empty.phone) == []


def test_preorder_is_allocated_before_checkout_even_when_worker_has_not_run(store, session):
    actor = store.authenticate("admin", "admin123").employee_id
    first = store.add_customer("Khách đặt trước đầu", "0987111101")
    second = store.add_customer("Khách đến sau", "0987111102")
    item = store.save_catalog_item(actor, item_type="MOVIE", title="Phim vừa phát hành",
                                   release_date=date.today() + timedelta(days=1))
    copy = store.add_copy(item.id, "RELEASE-RACE-001", actor_id=actor)
    store.reserve(first.id, [item.id], actor)
    store.save_catalog_item(actor, id=item.id, release_date=date.today())
    line = CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))
    with pytest.raises(BusinessError, match="không còn sẵn sàng"):
        store.quote(second.id, [line])
    session.expire_all()
    reservation = session.query(Reservation).filter_by(item_id=item.id, customer_id=first.id).one()
    assert reservation.state.value == "HELD" and reservation.allocated_copy_id == copy.id
    assert store.checkout_copies(item.id, LineAction.RENT, customer_id=second.id) == []
    assert store.checkout_copies(item.id, LineAction.RENT, customer_id=first.id)[0].copy_id == copy.id
    assert store.quote(first.id, [line]).deposit > 0


@pytest.mark.parametrize("entry_point", ["quote", "choices"])
def test_expired_hold_is_reassigned_when_customer_chooses_copy(store, session, entry_point):
    actor = store.authenticate("admin", "admin123").employee_id
    first = store.add_customer("Khách hết hạn giữ", "0987111103")
    second = store.add_customer("Khách chờ tiếp theo", "0987111104")
    item = store.save_catalog_item(actor, item_type="MOVIE", title="Đĩa hết hạn giữ")
    copy = store.add_copy(item.id, "EXPIRED-HOLD-001", actor_id=actor)
    store.reserve(first.id, [item.id], actor)
    store.reserve(second.id, [item.id], actor)
    session.expire_all()
    first_reservation = session.query(Reservation).filter_by(item_id=item.id, customer_id=first.id).one()
    first_reservation.hold_until = datetime.now(timezone.utc) - timedelta(seconds=1)
    session.flush()
    revision = store.cache_revision
    if entry_point == "quote":
        line = CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))
        assert store.quote(second.id, [line]).deposit > 0
    choices = store.checkout_copies(item.id, LineAction.RENT, customer_id=second.id)
    assert [choice.copy_id for choice in choices] == [copy.id]
    assert store.cache_revision > revision
    session.expire_all()
    assert session.query(Reservation).filter_by(id=first_reservation.id).one().state.value == "EXPIRED"
    second_reservation = session.query(Reservation).filter_by(item_id=item.id, customer_id=second.id).one()
    assert second_reservation.state.value == "HELD" and second_reservation.allocated_copy_id == copy.id


def test_catalog_item_is_materialized_before_session_closes(store):
    row = store.query_catalog().items[0]
    item = store.catalog_item(row.item_id)
    assert isinstance(item, CatalogItemView)
    assert item.title
    assert not hasattr(item, "_sa_instance_state")


def test_login_returns_materialized_account_and_preserves_audit(store, session):
    account = store.authenticate("admin", "admin123")
    assert isinstance(account, AccountView)
    assert account.employee_name
    assert account.role_code == RoleCode.ADMIN
    assert not hasattr(account, "_sa_instance_state")
    assert (
        session.scalar(
            select(AuditLog.id).where(
                AuditLog.actor_id == account.employee_id, AuditLog.action == "LOGIN_SUCCESS"
            )
        )
        is not None
    )


def test_search_uses_injected_provider_and_local_fallback(store):
    calls = []

    class Provider:
        def __init__(self, key, model, dimensions):
            calls.append((key, model, dimensions))

        def embed(self, text):
            return None

        def unavailable_reason(self):
            return "provider unavailable"

    store._integrations.gemini_api_key = lambda: "test-key"
    store._integrations.gemini_factory = Provider
    result = store.search_by_description_response("phim mẫu")
    assert calls == [("test-key", "gemini-embedding-001", 768)]
    assert result.mode == "LOCAL"
    assert result.warning == "provider unavailable"


def test_unit_of_work_rolls_back_flushed_changes_on_failure(session):
    factory = sessionmaker(
        bind=session.connection(), expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    with pytest.raises(RuntimeError, match="failed after flush"):
        with UnitOfWork(factory) as uow:
            uow.session.add(Customer(full_name="Rollback", phone="0987123988"))
            uow.session.flush()
            raise RuntimeError("failed after flush")
    assert session.scalar(select(Customer).where(Customer.phone == "0987123988")) is None


def test_checkout_and_partial_return_failure_are_atomic(store, session):
    account = store.authenticate("admin", "admin123")
    customer = store.add_customer("Khách giao dịch", "0987123989")
    item = CatalogItem(item_type=ItemType.MOVIE, title="Atomic checkout")
    session.add(item)
    session.flush()
    copy = PhysicalCopy(item_id=item.id, barcode="ATOMIC-TEST-COPY")
    session.add(copy)
    session.flush()
    order = store.checkout(
        customer.id,
        account.employee_id,
        
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, Decimal("500000"))],
    )
    term = session.scalar(select(RentalTerm).join(OrderLine).where(OrderLine.order_id == order.id))
    with pytest.raises(BusinessError, match="không còn hoạt động"):
        store.return_rentals(
            account.employee_id,
            customer.id,
            [(term.id, ReturnOutcome.NORMAL, ""), (-1, ReturnOutcome.NORMAL, "")],
        )
    session.expire_all()
    assert session.get(RentalTerm, term.id).state == RentalState.ACTIVE
    assert session.get(PhysicalCopy, copy.id).status == CopyStatus.RENTED
    assert (
        session.scalar(select(ReturnReceipt).where(ReturnReceipt.customer_id == customer.id))
        is None
    )


def test_shell_does_not_require_shift_controls():
    assert not hasattr(ShellMixin, "_open_shift")
    assert not hasattr(ShellMixin, "_close_shift")


def test_concurrent_service_calls_use_separate_units_of_work(monkeypatch):
    barrier = Barrier(3)

    class FakeUnit:
        def __init__(self):
            self.session = object()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

    class FakeOperations:
        def __init__(self, session, *args):
            self.session = session

        def dashboard(self):
            barrier.wait(timeout=5)
            return {"session": id(self.session)}

    settings = SimpleNamespace(
        gemini_embedding_model="model",
        gemini_embedding_dimensions=2,
        gemini_generation_model="model",
    )
    integrations = SimpleNamespace(settings=settings, gemini_api_key=lambda: None, gemini_factory=lambda *args: None)
    monkeypatch.setattr("normastore.application.services._StoreOperations", FakeOperations)
    store = StoreService(FakeUnit, integrations)
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(executor.map(lambda _: store.dashboard(), range(3)))
    assert len({result["session"] for result in results}) == 3


def test_read_cache_expires_and_writes_invalidate_without_caching_quote(monkeypatch):
    calls = {"dashboard": 0, "quote": 0, "write": 0}
    clock = [100.0]

    class FakeUnit:
        def __enter__(self):
            self.session = object()
            return self

        def __exit__(self, *args):
            pass

    class FakeOperations:
        def __init__(self, *_args):
            pass

        def dashboard(self):
            calls["dashboard"] += 1
            return {"count": calls["dashboard"]}

        def quote(self, *_args):
            calls["quote"] += 1
            return calls["quote"]

        def add_customer(self, *_args, **_kwargs):
            calls["write"] += 1
            return None

    settings = SimpleNamespace(gemini_embedding_model="model", gemini_embedding_dimensions=2, gemini_generation_model="model")
    integrations = SimpleNamespace(settings=settings, gemini_api_key=lambda: None, gemini_factory=lambda *args: None)
    monkeypatch.setattr("normastore.application.services._StoreOperations", FakeOperations)
    monkeypatch.setattr("normastore.application.services.monotonic", lambda: clock[0])
    store = StoreService(FakeUnit, integrations)
    result = store.dashboard()
    result["count"] = 999
    assert store.dashboard() == {"count": 1}
    assert store.quote(1, []) == 1 and store.quote(1, []) == 2
    clock[0] += 31
    assert store.dashboard() == {"count": 2}
    revision = store.cache_revision
    store.add_customer("A", "1")
    assert store.cache_revision == revision + 1
    assert store.dashboard() == {"count": 3}


def test_inflight_read_retries_after_write_instead_of_returning_stale_data(monkeypatch):
    started, release = Event(), Event()
    calls = []

    class FakeUnit:
        def __enter__(self):
            self.session = object()
            return self

        def __exit__(self, *args):
            pass

    class FakeOperations:
        def __init__(self, *_args):
            pass

        def dashboard(self):
            calls.append(len(calls) + 1)
            value = calls[-1]
            if value == 1:
                started.set()
                assert release.wait(5)
            return {"count": value}

        def add_customer(self, *_args, **_kwargs):
            return None

    settings = SimpleNamespace(gemini_embedding_model="model", gemini_embedding_dimensions=2, gemini_generation_model="model")
    integrations = SimpleNamespace(settings=settings, gemini_api_key=lambda: None, gemini_factory=lambda *args: None)
    monkeypatch.setattr("normastore.application.services._StoreOperations", FakeOperations)
    store = StoreService(FakeUnit, integrations)
    with ThreadPoolExecutor(max_workers=1) as executor:
        pending = executor.submit(store.dashboard)
        assert started.wait(5)
        store.add_customer("A", "1")
        release.set()
        assert pending.result()["count"] == 2
    assert store.dashboard()["count"] == 2
