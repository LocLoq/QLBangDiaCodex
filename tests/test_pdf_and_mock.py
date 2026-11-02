from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select

from normastore.application.contracts import CheckoutLine, PaymentInput
from normastore.application._operations import _StoreOperations
from normastore.domain.enums import CopyStatus, LineAction, PaymentMethod
from normastore.infrastructure.database.models import (
    AuditLog,
    Employee,
    Order,
    OrderLine,
    PhysicalCopy,
    Voucher,
)
from normastore.infrastructure.pdf_receipts import PdfReceiptExporter


def test_receipt_pdf_contains_scalar_order_data(session, tmp_path):
    service = _StoreOperations(session)
    customer = service.list_customers()[0]
    item = service.list_catalog()[0][0]
    copy = next(copy for copy in service.catalog_item(item.id).copies if copy.status == CopyStatus.AVAILABLE)
    employee_id = session.scalar(select(Employee.id).limit(1))
    order = service.checkout(
        customer.id,
        employee_id,
        None,
        [CheckoutLine(copy.id, LineAction.RENT, date.today() + timedelta(days=3))],
        [PaymentInput(PaymentMethod.CASH, Decimal("0"))],
    )
    session.flush()

    receipt = service.order_receipt(order.id)
    target = tmp_path / "receipt.pdf"
    thermal_target = tmp_path / "receipt-80mm.pdf"
    PdfReceiptExporter().export(receipt, target, "A4")
    PdfReceiptExporter().export(receipt, thermal_target, "80mm")
    service.record_order_pdf_export(order.id, employee_id, "A4", target.name)
    session.flush()

    assert target.read_bytes().startswith(b"%PDF-")
    assert thermal_target.read_bytes().startswith(b"%PDF-")
    assert receipt.lines[0].due_date == date.today() + timedelta(days=3)
    assert session.scalar(select(AuditLog).where(AuditLog.action == "EXPORT_ORDER_PDF")) is not None


def test_voucher_summary_reports_effective_state(session):
    service = _StoreOperations(session)
    employee_id = session.scalar(select(Employee.id).limit(1))
    service.create_voucher("PDF-ACTIVE", percent_off=Decimal("10"), actor_id=employee_id)
    service.create_voucher(
        "PDF-EXPIRED", percent_off=Decimal("10"), actor_id=employee_id,
        starts_on=date.today() - timedelta(days=5), ends_on=date.today() - timedelta(days=1),
    )
    session.flush()

    states = {voucher.code: voucher.effective_state for voucher in service.list_vouchers()}

    assert states["PDF-ACTIVE"] == "Đang hiệu lực"
    assert states["PDF-EXPIRED"] == "Hết hạn"


def test_mock_day_never_sells_copy_without_permission(session):
    service = _StoreOperations(session)
    employee_id = session.scalar(select(Employee.id).limit(1))
    copy = session.scalar(select(PhysicalCopy).where(PhysicalCopy.status == CopyStatus.AVAILABLE))
    assert copy is not None
    copy.can_sell = False
    session.flush()

    service.seed_mock_day(date.today(), employee_id, volume_per_day=1)
    session.flush()
    rows = session.execute(
        select(OrderLine, PhysicalCopy)
        .join(Order, Order.id == OrderLine.order_id)
        .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
        .where(Order.code.like(f"MOCK-{date.today():%Y%m%d}-%"))
    ).all()

    assert rows
    assert all(line.action != LineAction.BUY or (disk.can_sell and disk.item.can_sell) for line, disk in rows)


def test_mock_day_skips_voucher_expired_when_seed_runs(session, monkeypatch):
    class AlwaysSelectVoucher:
        def __init__(self, *_args):
            pass

        def random(self):
            return 0

        def randint(self, start, _end):
            return start

        def randrange(self, _stop):
            return 0

    monkeypatch.setattr("normastore.application._operations.Random", AlwaysSelectVoucher)
    service = _StoreOperations(session)
    employee_id = session.scalar(select(Employee.id).limit(1))
    business_date = date.today() - timedelta(days=2)
    session.add(Voucher(
        code="MOCKV-EXPIRED",
        percent_off=Decimal("10"),
        starts_on=business_date - timedelta(days=1),
        ends_on=date.today() - timedelta(days=1),
    ))
    session.flush()

    service.seed_mock_day(business_date, employee_id, volume_per_day=1)
    session.flush()

    assert session.scalar(select(Order.id).where(Order.code.like(f"MOCK-{business_date:%Y%m%d}-%")))
