from __future__ import annotations

from sqlalchemy import delete, desc, func, select

from normastore.application.contracts import (
    PagedResult,
    PageRequest,
    SortSpec,
)
from normastore.infrastructure.database.models import (
    Customer,
    PaymentTransaction,
    PremiumMembership,
    PremiumPlan,
    PremiumSettings,
    RecommendationCache,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class CustomerQueries:
    def __init__(self, session):
        self.session = session

    def customer(self, customer_id: int, *, lock: bool = False):
        return self.session.get(Customer, customer_id, with_for_update=lock)

    def premium_settings(self):
        return self.session.get(PremiumSettings, 1)

    def premium_plans(self, include_inactive=False):
        statement = select(PremiumPlan).order_by(PremiumPlan.days)
        if not include_inactive:
            statement = statement.where(PremiumPlan.active.is_(True))
        return list(self.session.scalars(statement))

    def premium_plan(self, days):
        return self.session.get(PremiumPlan, days)

    def save_premium_plan(self, plan):
        self.session.add(plan)
        self.session.flush()

    def scheduled_memberships(self, customer_id, today):
        return list(self.session.scalars(select(PremiumMembership).where(
            PremiumMembership.customer_id == customer_id,
            PremiumMembership.starts_on > today,
            PremiumMembership.cancelled_on.is_(None),
        ).order_by(PremiumMembership.starts_on, PremiumMembership.id).with_for_update()))

    def add_membership(self, membership):
        self.session.add(membership)
        self.session.flush()

    def customer_by_phone(self, phone: str):
        return self.session.scalar(select(Customer).where(Customer.phone == phone))

    def premium_active(self, customer_id: int, on_date):
        return (
            self.session.scalar(
                select(PremiumMembership.id).where(
                    PremiumMembership.customer_id == customer_id,
                    PremiumMembership.active_on(on_date),
                )
            )
            is not None
        )

    def premium_until(self, customer_id: int, on_date):
        return self.session.scalar(select(func.max(PremiumMembership.ends_on)).where(
            PremiumMembership.customer_id == customer_id,
            PremiumMembership.active_on(on_date),
        ))

    def active_memberships(self, customer_id: int, on_date):
        return self.session.scalars(
            select(PremiumMembership)
            .where(PremiumMembership.customer_id == customer_id, PremiumMembership.active_on(on_date))
            .order_by(PremiumMembership.ends_on.desc(), PremiumMembership.id.desc())
            .with_for_update()
        ).all()

    def save_customer(self, customer: Customer):
        self.session.add(customer)
        self.session.flush()

    def delete_customer(self, customer: Customer):
        self.session.execute(
            delete(RecommendationCache).where(RecommendationCache.customer_id == customer.id)
        )
        self.session.delete(customer)
        self.session.flush()

    def save_membership(self, membership: PremiumMembership, payment: PaymentTransaction):
        self.session.add_all((membership, payment))
        self.session.flush()

    def query_customers(
        self, text: str = "", page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec()
    ) -> PagedResult[Customer]:
        stmt = select(Customer).order_by(Customer.full_name)
        if text.strip():
            pattern = f"%{text.strip()}%"
            stmt = stmt.where((Customer.full_name.like(pattern)) | (Customer.phone.like(pattern)))
        fields = {
            "title": Customer.full_name,
            "phone": Customer.phone,
            "email": Customer.email,
        }
        expression = fields.get(sort.field, Customer.full_name)
        stmt = stmt.order_by(None).order_by(
            desc(expression) if sort.descending else expression.asc(), Customer.id
        )
        page = page_rows(self.session, stmt, page_request)
        return PagedResult(
            tuple(row[0] for row in page.items),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )

    def query_customers_with_premium(self, text, page_request, on_date):
        active = select(PremiumMembership.id).where(
            PremiumMembership.customer_id == Customer.id,
            PremiumMembership.active_on(on_date),
        ).exists()
        stmt = select(Customer, active).order_by(Customer.full_name, Customer.id)
        if text.strip():
            pattern = f"%{text.strip()}%"
            stmt = stmt.where((Customer.full_name.like(pattern)) | (Customer.phone.like(pattern)))
        page = page_rows(self.session, stmt, page_request)
        return PagedResult(tuple((customer, bool(premium)) for customer, premium in page.items),
                           page.page, page.page_size, page.total_items, page.total_pages)
