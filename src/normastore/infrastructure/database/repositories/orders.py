from __future__ import annotations

from datetime import timedelta
from decimal import ROUND_DOWN, Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import joinedload

from normastore.application.contracts import (
    ActiveRental,
    OrderSummary,
    PagedResult,
    PageRequest,
    SortSpec,
)
from normastore.domain.business_time import utc_start_of_day
from normastore.domain.enums import (
    CopyStatus,
    LineAction,
    RentalState,
    ReservationState,
)
from normastore.infrastructure.database.models import (
    Customer,
    Employee,
    Order,
    OrderDiscount,
    OrderLine,
    PaymentTransaction,
    PhysicalCopy,
    RentalTerm,
    Reservation,
    SaleReturn,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class OrderQueries:
    def __init__(self, session):
        self.session = session

    def query_active_rentals(
        self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("due", False), customer_name: str = ""
    ) -> PagedResult[ActiveRental]:
        stmt = (
            select(RentalTerm, OrderLine, Order, Customer, PhysicalCopy)
            .join(OrderLine, RentalTerm.line_id == OrderLine.id)
            .join(Order, OrderLine.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .join(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .where(RentalTerm.state == RentalState.ACTIVE)
            .options(joinedload(PhysicalCopy.item))
        )
        if customer_name.strip():
            stmt = stmt.where(Customer.full_name.ilike(f"%{customer_name.strip()}%"))
        fields = {
            "title": OrderLine.title_snapshot,
            "customer": Customer.full_name,
            "due": RentalTerm.due_date,
            "status": RentalTerm.due_date,
        }
        expression = fields.get(sort.field, RentalTerm.due_date)
        page = page_rows(
            self.session,
            stmt.order_by(desc(expression) if sort.descending else expression.asc(), RentalTerm.id),
            page_request,
        )
        balances, deposits = self.rental_order_amounts(row[2] for row in page.items)
        return PagedResult(
            tuple(
                ActiveRental(
                    term.id,
                    customer.id,
                    customer.full_name,
                    line.title_snapshot,
                    copy.barcode,
                    term.due_date,
                    term.late_daily_rate,
                    copy.condition,
                    copy.condition_percent,
                    copy.aisle,
                    copy.rack,
                    copy.compartment,
                    deposit_amount=Decimal(line.deposit_amount),
                    replacement_value=Decimal(copy.item.replacement_value),
                    deposit_paid=deposits[line.id],
                    order_code=order.code,
                    order_balance_due=balances[order.id],
                )
                for term, line, order, customer, copy in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )

    def rental_order_amounts(self, orders):
        orders_by_id = {order.id: order for order in orders}
        if not orders_by_id:
            return {}, {}
        paid_by_order = dict(self.session.execute(
            select(PaymentTransaction.order_id, func.sum(PaymentTransaction.amount))
            .where(PaymentTransaction.order_id.in_(orders_by_id),
                   PaymentTransaction.category == "CHECKOUT")
            .group_by(PaymentTransaction.order_id)
        ).all())
        zero = Decimal("0")
        balances = {}
        paid_deposits = {}
        for order in orders_by_id.values():
            total_due = order.gross_total - order.discount_total + order.deposit_total
            # Confirmed legacy and demo orders may have no checkout transaction.
            fallback = total_due if order.status == "CONFIRMED" else zero
            paid = max(zero, paid_by_order.get(order.id, fallback))
            balances[order.id] = max(zero, total_due - paid)
            paid_deposits[order.id] = min(order.deposit_total, paid)

        deposits = {}
        cumulative_due = dict.fromkeys(orders_by_id, zero)
        cumulative_paid = dict.fromkeys(orders_by_id, zero)
        for order_id, line_id, amount in self.session.execute(
            select(OrderLine.order_id, OrderLine.id, OrderLine.deposit_amount)
            .where(OrderLine.order_id.in_(orders_by_id), OrderLine.action == LineAction.RENT)
            .order_by(OrderLine.order_id, OrderLine.id)
        ):
            deposit_total = orders_by_id[order_id].deposit_total
            paid = paid_deposits[order_id]
            if paid == deposit_total:
                deposits[line_id] = amount
                continue
            # Round cumulative shares so returning lines in any order preserves the total.
            cumulative_due[order_id] += amount
            share = (cumulative_due[order_id] * paid / deposit_total).quantize(
                Decimal("0.01"), rounding=ROUND_DOWN
            )
            deposits[line_id] = share - cumulative_paid[order_id]
            cumulative_paid[order_id] = share
        return balances, deposits

    def query_orders(
        self,
        text: str = "",
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("created_at", True),
    ) -> PagedResult[OrderSummary]:
        stmt = (
            select(Order, Customer, Employee)
            .join(Customer, Order.customer_id == Customer.id)
            .join(Employee, Order.employee_id == Employee.id)
        )
        if text.strip():
            term = f"%{text.strip()}%"
            stmt = stmt.where((Order.code.like(term)) | (Customer.full_name.like(term)))
        total_due = Order.gross_total - Order.discount_total + Order.deposit_total - func.coalesce(Order.deposit_applied, 0)
        fields = {
            "title": Order.code,
            "customer": Customer.full_name,
            "employee": Employee.full_name,
            "created": Order.created_at,
            "created_at": Order.created_at,
            "status": Order.status,
            "total": total_due,
        }
        expression = fields.get(sort.field, Order.created_at)
        stmt = stmt.order_by(desc(expression) if sort.descending else expression.asc(), Order.id)
        page = page_rows(self.session, stmt, page_request)
        return PagedResult(
            tuple(
                OrderSummary(
                    order.id,
                    order.code,
                    customer.full_name,
                    employee.full_name,
                    order.created_at,
                    order.status,
                    Decimal(order.gross_total)
                    - Decimal(order.discount_total)
                    + Decimal(order.deposit_total)
                    - Decimal(order.deposit_applied or 0),
                )
                for order, customer, employee in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )


    def fetch_quote_copies(self, lines):
        return self.session.scalars(
            select(PhysicalCopy)
            .options(joinedload(PhysicalCopy.item))
            .where(PhysicalCopy.id.in_([line.copy_id for line in lines]))
        )

    def fetch_checkout_check(self, code):
        return self.session.scalar(select(Order.id).where(Order.code == code))

    def fetch_checkout_locked(self, lines):
        return self.session.scalars(
            select(PhysicalCopy)
            .options(joinedload(PhysicalCopy.item))
            .where(PhysicalCopy.id.in_([x.copy_id for x in lines]))
            .with_for_update()
        )

    def order_lines_with_copies(self, order_id):
        return self.session.execute(
            select(OrderLine, PhysicalCopy, RentalTerm)
            .outerjoin(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .outerjoin(RentalTerm, RentalTerm.line_id == OrderLine.id)
            .where(OrderLine.order_id == order_id)
            .order_by(OrderLine.id)
        )

    def order_with_parties(self, order_id):
        return self.session.execute(
            select(Order, Customer, Employee)
            .join(Customer, Order.customer_id == Customer.id)
            .join(Employee, Order.employee_id == Employee.id)
            .where(Order.id == order_id)
        )



    def fetch_order_receipt_discounts(self, order_id):
        return self.session.scalars(
            select(OrderDiscount)
            .where(OrderDiscount.order_id == order_id)
            .order_by(OrderDiscount.id)
        )

    def fetch_order_receipt_payments(self, order_id):
        return self.session.scalars(
            select(PaymentTransaction)
            .where(PaymentTransaction.order_id == order_id)
            .order_by(PaymentTransaction.created_at, PaymentTransaction.id)
        )

    def get_order_line(self, identifier):
        return self.session.get(OrderLine, identifier)

    def fetch_return_rentals_term(self, term_id):
        return self.session.scalar(
            select(RentalTerm)
            .options(
                joinedload(RentalTerm.line).joinedload(OrderLine.order),
                joinedload(RentalTerm.line)
                .joinedload(OrderLine.copy)
                .joinedload(PhysicalCopy.item),
            )
            .where(RentalTerm.id == term_id)
            .with_for_update()
        )

    def fetch_extend_rental_term(self, rental_term_id):
        return self.session.scalar(
            select(RentalTerm)
            .options(joinedload(RentalTerm.line).joinedload(OrderLine.copy))
            .where(RentalTerm.id == rental_term_id)
            .with_for_update()
        )

    def fetch_extend_rental_has_waiting_reservation(self, term):
        return self.session.scalar(
            select(Reservation.id).where(
                Reservation.item_id == term.line.copy.item_id,
                Reservation.state == ReservationState.WAITING,
            )
        )

    def fetch_rental_to_sale_term(self, rental_term_id):
        return self.session.scalar(
            select(RentalTerm)
            .options(
                joinedload(RentalTerm.line).joinedload(OrderLine.copy).joinedload(PhysicalCopy.item)
            )
            .where(RentalTerm.id == rental_term_id)
            .with_for_update()
        )

    def fetch_returnable_sales_rows(self, today):
        return self.session.execute(
            select(OrderLine, Order, Customer, PhysicalCopy)
            .join(Order, OrderLine.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .join(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .where(
                OrderLine.action == LineAction.BUY,
                PhysicalCopy.status == CopyStatus.SOLD,
                Order.created_at >= utc_start_of_day(today - timedelta(days=7)),
                ~select(SaleReturn.id).where(SaleReturn.sale_line_id == OrderLine.id).exists(),
            )
            .order_by(Order.created_at.desc())
        )

    def fetch_return_sale_line(self, sale_line_id):
        return self.session.scalar(
            select(OrderLine)
            .options(joinedload(OrderLine.copy), joinedload(OrderLine.order))
            .where(OrderLine.id == sale_line_id, OrderLine.action == LineAction.BUY,
                   ~select(SaleReturn.id).where(SaleReturn.sale_line_id == OrderLine.id).exists())
            .with_for_update()
        )

    def add_notification_outbox(self, value):
        self.session.add(value)

    def add_order(self, value):
        self.session.add(value)

    def add_order_discount(self, value):
        self.session.add(value)

    def add_order_line(self, value):
        self.session.add(value)

    def add_payment_transaction(self, value):
        self.session.add(value)

    def add_penalty_charge(self, value):
        self.session.add(value)

    def add_rental_extension(self, value):
        self.session.add(value)

    def add_rental_term(self, value):
        self.session.add(value)

    def add_return_line(self, value):
        self.session.add(value)

    def add_return_receipt(self, value):
        self.session.add(value)

    def add_sale_return(self, value):
        self.session.add(value)

    def flush(self):
        self.session.flush()

    def get_customer(self, identifier):
        return self.session.get(Customer, identifier)

    def get_order(self, identifier):
        return self.session.get(Order, identifier)
