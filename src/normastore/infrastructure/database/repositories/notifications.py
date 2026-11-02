from __future__ import annotations

from sqlalchemy import desc, select

from normastore.application.contracts import (
    NotificationSummary,
    PagedResult,
    PageRequest,
    SortSpec,
)
from normastore.domain.enums import NotificationStatus
from normastore.infrastructure.database.models import (
    Customer,
    NotificationOutbox,
    OrderLine,
    RentalTerm,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class NotificationQueries:
    def __init__(self, session):
        self.session = session

    def due_reminders(self, now):
        return self.session.execute(
            select(NotificationOutbox, RentalTerm, OrderLine, Customer)
            .outerjoin(RentalTerm, NotificationOutbox.rental_term_id == RentalTerm.id)
            .outerjoin(OrderLine, RentalTerm.line_id == OrderLine.id)
            .join(Customer, NotificationOutbox.customer_id == Customer.id)
            .where(
                NotificationOutbox.status.in_(
                    [NotificationStatus.PENDING, NotificationStatus.FAILED]
                ),
                NotificationOutbox.scheduled_for <= now,
            )
            .order_by(NotificationOutbox.scheduled_for, NotificationOutbox.id)
            .with_for_update()
        ).all()

    def query_notifications(
        self,
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("scheduled", True),
    ) -> PagedResult[NotificationSummary]:
        rows = select(NotificationOutbox, Customer).join(
            Customer, NotificationOutbox.customer_id == Customer.id
        )
        fields = {
            "customer": Customer.full_name,
            "channel": NotificationOutbox.channel,
            "event": NotificationOutbox.event,
            "scheduled": NotificationOutbox.scheduled_for,
            "status": NotificationOutbox.status,
            "attempts": NotificationOutbox.attempts,
        }
        expression = fields.get(sort.field, NotificationOutbox.scheduled_for)
        page = page_rows(
            self.session,
            rows.order_by(
                desc(expression) if sort.descending else expression.asc(), NotificationOutbox.id
            ),
            page_request,
        )
        return PagedResult(
            tuple(
                NotificationSummary(
                    outbox.id,
                    customer.full_name,
                    outbox.channel,
                    outbox.event,
                    outbox.scheduled_for,
                    str(outbox.status),
                    outbox.attempts,
                    outbox.error,
                )
                for outbox, customer in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )
