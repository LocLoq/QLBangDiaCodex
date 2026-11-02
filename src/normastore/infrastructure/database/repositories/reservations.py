from __future__ import annotations

from sqlalchemy import desc, select

from normastore.application.contracts import (
    PagedResult,
    PageRequest,
    ReservationView,
    SortSpec,
)
from normastore.domain.enums import CopyStatus, ReservationState
from normastore.infrastructure.database.models import (
    CatalogItem,
    Customer,
    PhysicalCopy,
    Reservation,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class ReservationQueries:
    def __init__(self, session):
        self.session = session

    def query_reservations(
        self, page_request: PageRequest = PageRequest(), sort: SortSpec = SortSpec("created", True)
    ) -> PagedResult[ReservationView]:
        stmt = (
            select(Reservation, Customer, CatalogItem)
            .join(Customer, Reservation.customer_id == Customer.id)
            .join(CatalogItem, Reservation.item_id == CatalogItem.id)
        )
        fields = {
            "customer": Customer.full_name,
            "item": CatalogItem.title,
            "state": Reservation.state,
            "hold": Reservation.hold_until,
            "created": Reservation.created_at,
        }
        expression = fields.get(sort.field, Reservation.created_at)
        page = page_rows(
            self.session,
            stmt.order_by(
                desc(expression) if sort.descending else expression.asc(), Reservation.id
            ),
            page_request,
        )
        return PagedResult(
            tuple(
                ReservationView(
                    reservation.id,
                    customer.full_name,
                    item.title,
                    reservation.state,
                    reservation.hold_until,
                )
                for reservation, customer, item in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )

    def fetch_reserve_items(self, item_ids):
        return self.session.scalars(
            select(CatalogItem).where(
                CatalogItem.id.in_(set(item_ids)), CatalogItem.archived.is_(False)
            )
        )

    def fetch_reserve_duplicate(self, customer_id, item_id):
        return self.session.scalar(
            select(Reservation.id).where(
                Reservation.customer_id == customer_id,
                Reservation.item_id == item_id,
                Reservation.state.in_([ReservationState.WAITING, ReservationState.HELD]),
            )
        )

    def fetch_expire_reservation_holds_reservations(self, now):
        return self.session.scalars(
            select(Reservation)
            .where(Reservation.state == ReservationState.HELD, Reservation.hold_until <= now)
            .with_for_update()
        )

    def fetch_expire_reservation_holds_copy(self, reservation):
        return self.session.scalar(
            select(PhysicalCopy)
            .where(PhysicalCopy.id == reservation.allocated_copy_id)
            .with_for_update()
        )

    def fetch_allocate_waiting_reservations_copies(self, item_id):
        return self.session.scalars(
            select(PhysicalCopy)
            .where(PhysicalCopy.item_id == item_id, PhysicalCopy.status == CopyStatus.AVAILABLE)
            .order_by(PhysicalCopy.id)
            .with_for_update()
        )

    def fetch_allocate_waiting_reservations_reservations(self, item_id):
        return self.session.scalars(
            select(Reservation)
            .where(Reservation.item_id == item_id, Reservation.state == ReservationState.WAITING)
            .order_by(Reservation.created_at)
            .with_for_update()
        )

    def add_reservation(self, value):
        self.session.add(value)

    def flush(self):
        self.session.flush()

    def get_customer(self, identifier):
        return self.session.get(Customer, identifier)
