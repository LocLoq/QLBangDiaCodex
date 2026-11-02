from __future__ import annotations

import random
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from normastore.domain.enums import CopyStatus, LineAction, PaymentMethod, RentalState
from normastore.infrastructure.database.models import (
    Customer,
    Employee,
    Order,
    OrderLine,
    PaymentTransaction,
    RentalTerm,
)
from normastore.infrastructure.database.repositories.demo_seed import DemoSeedRepository

SURNAMES = (
    "Nguyễn",
    "Trần",
    "Lê",
    "Phạm",
    "Hoàng",
    "Võ",
    "Đặng",
    "Bùi",
    "Đỗ",
    "Hồ",
    "Ngô",
    "Dương",
)
MIDDLE_NAMES = (
    "Minh",
    "Thanh",
    "Gia",
    "Quốc",
    "Bảo",
    "Ngọc",
    "Thùy",
    "Khánh",
    "Phương",
    "Anh",
    "Hữu",
    "Đức",
    "Mỹ",
    "Tuấn",
    "Thiên",
    "Kim",
    "Quỳnh",
    "Hải",
    "Đình",
    "Tường",
)
GIVEN_NAMES = (
    "Anh",
    "Hân",
    "Linh",
    "Minh",
    "Nam",
    "Trang",
    "Huy",
    "Vy",
    "Khang",
    "Nhi",
    "Phúc",
    "Thảo",
    "Quân",
    "My",
    "Đạt",
    "Yến",
    "Long",
    "Trâm",
    "Dũng",
    "Lan",
    "Kiệt",
    "Mai",
    "Tín",
    "Nhiên",
    "Sơn",
)


def vietnamese_name(index: int) -> str:
    """Return a deterministic, natural Vietnamese name; unique for the first 6,000 rows."""
    surname = SURNAMES[index % len(SURNAMES)]
    middle = MIDDLE_NAMES[(index // len(SURNAMES)) % len(MIDDLE_NAMES)]
    given = GIVEN_NAMES[(index // (len(SURNAMES) * len(MIDDLE_NAMES))) % len(GIVEN_NAMES)]
    return f"{surname} {middle} {given}"


def seed_demo(uow_factory, target_orders: int):
    rng = random.Random(20260903)
    with uow_factory() as uow:
        repo = DemoSeedRepository(uow.session)
        for customer in repo.sample_customers():
            customer.full_name = vietnamese_name(customer.id)
        for employee in repo.sample_employees():
            employee.full_name = vietnamese_name(employee.id + 1000)
        existing = repo.customer_count()
        for index in range(existing + 1, 1001):
            repo.add_customer(
                Customer(
                    full_name=vietnamese_name(index),
                    phone=f"098{index:07d}",
                    reputation_score=rng.randint(45, 98),
                )
            )
        if repo.employee_count() < 12:
            for index in range(repo.employee_count() + 1, 13):
                repo.add_employee(
                    Employee(full_name=vietnamese_name(index + 1000), phone=f"091{index:07d}")
                )
        uow.commit()
    with uow_factory() as uow:
        repo = DemoSeedRepository(uow.session)
        customers = list(repo.customers())
        employees = list(repo.employees())
        copies = [
            copy
            for copy in repo.available_copies()
            if (copy.can_rent and copy.item.can_rent) or (copy.can_sell and copy.item.can_sell)
        ]
        if not copies:
            raise SystemExit("Kho không có copy AVAILABLE để seed giao dịch.")
        existing = repo.order_count()
        target = max(existing, target_orders)
        active_copies: set[int] = set()
        for index in range(existing + 1, target + 1):
            customer, employee = rng.choice(customers), rng.choice(employees)
            copy = rng.choice(copies)
            created = datetime.now(timezone.utc) - timedelta(days=rng.randint(1, 540))
            rentable = copy.can_rent and copy.item.can_rent
            sellable = copy.can_sell and copy.item.can_sell
            action = (
                LineAction.BUY
                if sellable and (not rentable or rng.random() < 0.20)
                else LineAction.RENT
            )
            order = Order(
                code=f"MOCK{index:08d}",
                customer_id=customer.id,
                employee_id=employee.id,
                status="CONFIRMED",
                gross_total=copy.item.sale_price
                if action == LineAction.BUY
                else copy.item.rental_price,
                discount_total=Decimal("0"),
                deposit_total=copy.item.deposit_amount
                if action == LineAction.RENT
                else Decimal("0"),
                created_at=created,
                updated_at=created,
            )
            repo.add_order(order)
            price = copy.item.sale_price if action == LineAction.BUY else copy.item.rental_price
            line = OrderLine(
                order_id=order.id,
                copy_id=copy.id,
                action=action,
                title_snapshot=copy.item.title,
                unit_price=price,
                deposit_amount=copy.item.deposit_amount
                if action == LineAction.RENT
                else Decimal("0"),
            )
            repo.add_order_line(line)
            if action == LineAction.RENT:
                active = rng.random() < 0.04 and copy.id not in active_copies
                due = (
                    date.today() + timedelta(days=rng.randint(-10, 5))
                    if active
                    else created.date() + timedelta(days=3)
                )
                term = RentalTerm(
                    line_id=line.id,
                    due_date=due,
                    state=RentalState.ACTIVE if active else RentalState.RETURNED,
                    returned_on=None if active else due,
                    issued_condition=copy.condition,
                )
                repo.add_rental_term(term)
                if active:
                    copy.status = CopyStatus.RENTED
                    active_copies.add(copy.id)
                    copies.remove(copy)
            else:
                # Keep most mock sales historical so the catalog remains usable; a small fraction is sold out.
                if rng.random() < 0.08:
                    copy.status = CopyStatus.SOLD
                    copies.remove(copy)
            repo.add_payment(
                PaymentTransaction(
                    order_id=order.id,
                    customer_id=customer.id,
                    employee_id=employee.id,
                    method=PaymentMethod.CASH,
                    category="MOCK",
                    amount=price,
                )
            )
            if index % 500 == 0:
                uow.commit()
        uow.commit()
    return target - existing, target
