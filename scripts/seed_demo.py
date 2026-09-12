from __future__ import annotations

import argparse
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.domain.enums import CopyStatus, LineAction, PaymentMethod, RentalState
from normastore.infrastructure.database import (
    Customer,
    Employee,
    Order,
    OrderLine,
    PaymentTransaction,
    PhysicalCopy,
    RentalTerm,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


SURNAMES = ("Nguyễn", "Trần", "Lê", "Phạm", "Hoàng", "Võ", "Đặng", "Bùi", "Đỗ", "Hồ", "Ngô", "Dương")
MIDDLE_NAMES = ("Minh", "Thanh", "Gia", "Quốc", "Bảo", "Ngọc", "Thùy", "Khánh", "Phương", "Anh", "Hữu", "Đức", "Mỹ", "Tuấn", "Thiên", "Kim", "Quỳnh", "Hải", "Đình", "Tường")
GIVEN_NAMES = ("Anh", "Hân", "Linh", "Minh", "Nam", "Trang", "Huy", "Vy", "Khang", "Nhi", "Phúc", "Thảo", "Quân", "My", "Đạt", "Yến", "Long", "Trâm", "Dũng", "Lan", "Kiệt", "Mai", "Tín", "Nhiên", "Sơn")


def vietnamese_name(index: int) -> str:
    """Return a deterministic, natural Vietnamese name; unique for the first 6,000 rows."""
    surname = SURNAMES[index % len(SURNAMES)]
    middle = MIDDLE_NAMES[(index // len(SURNAMES)) % len(MIDDLE_NAMES)]
    given = GIVEN_NAMES[(index // (len(SURNAMES) * len(MIDDLE_NAMES))) % len(GIVEN_NAMES)]
    return f"{surname} {middle} {given}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--orders", type=int, default=25000)
    args = parser.parse_args()
    factory = bootstrap(Settings()); rng = random.Random(20260903)
    with factory() as session:
        for customer in session.query(Customer).filter(Customer.full_name.like("Khách hàng mẫu %")):
            customer.full_name = vietnamese_name(customer.id)
        for employee in session.query(Employee).filter(Employee.full_name.like("Nhân viên mẫu %")):
            employee.full_name = vietnamese_name(employee.id + 1000)
        existing = session.query(Customer).count()
        for index in range(existing + 1, 1001):
            session.add(Customer(full_name=vietnamese_name(index), phone=f"098{index:07d}", reputation_score=rng.randint(45, 98)))
        if session.query(Employee).count() < 12:
            for index in range(session.query(Employee).count() + 1, 13): session.add(Employee(full_name=vietnamese_name(index + 1000), phone=f"091{index:07d}"))
        session.commit()
    with factory() as session:
        customers = list(session.query(Customer).all())
        employees = list(session.query(Employee).all())
        copies = [
            copy for copy in session.query(PhysicalCopy).filter(PhysicalCopy.status == CopyStatus.AVAILABLE).all()
            if (copy.can_rent and copy.item.can_rent) or (copy.can_sell and copy.item.can_sell)
        ]
        if not copies:
            raise SystemExit("Kho không có copy AVAILABLE để seed giao dịch.")
        existing = session.query(Order).count()
        target = max(existing, args.orders)
        active_copies: set[int] = set()
        for index in range(existing + 1, target + 1):
            customer, employee = rng.choice(customers), rng.choice(employees)
            copy = rng.choice(copies)
            created = datetime.now(timezone.utc) - timedelta(days=rng.randint(1, 540))
            rentable = copy.can_rent and copy.item.can_rent
            sellable = copy.can_sell and copy.item.can_sell
            action = LineAction.BUY if sellable and (not rentable or rng.random() < 0.20) else LineAction.RENT
            order = Order(code=f"MOCK{index:08d}", customer_id=customer.id, employee_id=employee.id, status="CONFIRMED", gross_total=copy.item.sale_price if action == LineAction.BUY else copy.item.rental_price, discount_total=Decimal("0"), deposit_total=copy.item.deposit_amount if action == LineAction.RENT else Decimal("0"), created_at=created, updated_at=created)
            session.add(order); session.flush()
            price = copy.item.sale_price if action == LineAction.BUY else copy.item.rental_price
            line = OrderLine(order_id=order.id, copy_id=copy.id, action=action, title_snapshot=copy.item.title, unit_price=price, deposit_amount=copy.item.deposit_amount if action == LineAction.RENT else Decimal("0"))
            session.add(line); session.flush()
            if action == LineAction.RENT:
                active = rng.random() < 0.04 and copy.id not in active_copies
                due = date.today() + timedelta(days=rng.randint(-10, 5)) if active else created.date() + timedelta(days=3)
                term = RentalTerm(line_id=line.id, due_date=due, state=RentalState.ACTIVE if active else RentalState.RETURNED, returned_on=None if active else due, issued_condition=copy.condition)
                session.add(term)
                if active:
                    copy.status = CopyStatus.RENTED; active_copies.add(copy.id); copies.remove(copy)
            else:
                # Keep most mock sales historical so the catalog remains usable; a small fraction is sold out.
                if rng.random() < 0.08:
                    copy.status = CopyStatus.SOLD
                    copies.remove(copy)
            session.add(PaymentTransaction(order_id=order.id, customer_id=customer.id, employee_id=employee.id, method=PaymentMethod.CASH, category="MOCK", amount=price))
            if index % 500 == 0:
                session.commit()
        session.commit()
    print(f"Đã seed {target - existing} phiếu mock nhất quán (mục tiêu {target}).")


if __name__ == "__main__": main()
