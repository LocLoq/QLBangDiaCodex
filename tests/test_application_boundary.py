from concurrent.futures import ThreadPoolExecutor
from datetime import date, timedelta
from decimal import Decimal
from functools import partial
from threading import Barrier
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from normastore.application.contracts import (
    AccountView,
    BusinessError,
    CatalogItemView,
    CheckoutLine,
    CustomerView,
    PaymentInput,
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
    PhysicalCopy,
    RentalTerm,
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
        None,
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


def test_shift_buttons_use_employee_id(monkeypatch):
    calls = []
    fake = SimpleNamespace(
        account=AccountView(47, 3, "user", "Nhân viên", RoleCode.STAFF, "Nhân viên", False),
        current_shift=SimpleNamespace(id=8),
        store=SimpleNamespace(
            open_shift=lambda *args: calls.append(("open", args)),
            close_shift=lambda *args: calls.append(("close", args)),
        ),
        _refresh_status=lambda: None,
    )
    monkeypatch.setattr("normastore.ui.shell.simpledialog.askfloat", lambda *args, **kwargs: 50)
    ShellMixin._open_shift(fake)
    fake.current_shift = SimpleNamespace(id=8)
    ShellMixin._close_shift(fake)
    assert calls == [("open", (3, Decimal("50"))), ("close", (8, Decimal("50"), 3))]


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
