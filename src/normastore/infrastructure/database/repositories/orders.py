from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import desc, func, select
from sqlalchemy.orm import joinedload

from normastore.application.contracts import (
    ActiveRental,
    OrderSummary,
    PagedResult,
    PageRequest,
    SortSpec,
)
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
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class OrderQueries:
    def __init__(self, session):
        self.session = session

    def query_active_rentals(
        self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("due", False)
    ) -> PagedResult[ActiveRental]:
        stmt = (
            select(RentalTerm, OrderLine, Order, Customer, PhysicalCopy)
            .join(OrderLine, RentalTerm.line_id == OrderLine.id)
            .join(Order, OrderLine.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .join(PhysicalCopy, OrderLine.copy_id == PhysicalCopy.id)
            .where(RentalTerm.state == RentalState.ACTIVE)
        )
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
        return PagedResult(
            tuple(
                ActiveRental(
                    term.id,
                    customer.id,
                    customer.full_name,
                    line.title_snapshot,
                    copy.barcode,
                    term.due_date,
                )
                for term, line, _order, customer, copy in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )

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
        total_due = Order.gross_total - Order.discount_total + Order.deposit_total
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
                    + Decimal(order.deposit_total),
                )
                for order, customer, employee in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )

    def fetch_open_rental_count_rows(self, customer_id):
        return self.session.scalar(
            select(func.count(RentalTerm.id))
            .join(OrderLine)
            .join(Order)
            .where(Order.customer_id == customer_id, RentalTerm.state == RentalState.ACTIVE)
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
                Order.created_at
                >= datetime.combine(
                    today - timedelta(days=7), datetime.min.time(), tzinfo=timezone.utc
                ),
            )
            .order_by(Order.created_at.desc())
        )

    def fetch_return_sale_line(self, sale_line_id):
        return self.session.scalar(
            select(OrderLine)
            .options(joinedload(OrderLine.copy), joinedload(OrderLine.order))
            .where(OrderLine.id == sale_line_id, OrderLine.action == LineAction.BUY)
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
