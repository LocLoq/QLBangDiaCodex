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

    def expired_hold_copy_ids(self, now, item_id=None):
        statement = select(Reservation.allocated_copy_id).where(
            Reservation.state == ReservationState.HELD, Reservation.hold_until <= now,
            Reservation.allocated_copy_id.is_not(None),
        )
        if item_id is not None:
            statement = statement.where(Reservation.item_id == item_id)
        return self.session.scalars(statement.distinct().order_by(Reservation.allocated_copy_id)).all()

    def lock_copies(self, copy_ids):
        if copy_ids:
            self.session.execute(select(PhysicalCopy.id).where(PhysicalCopy.id.in_(copy_ids))
                                 .order_by(PhysicalCopy.id).with_for_update()).all()

    def fetch_expire_reservation_holds_reservations(self, now, item_id=None):
        statement = select(Reservation).where(
            Reservation.state == ReservationState.HELD, Reservation.hold_until <= now
        )
        if item_id is not None:
            statement = statement.where(Reservation.item_id == item_id)
        return self.session.scalars(statement.order_by(Reservation.id).with_for_update())

    def fetch_expire_reservation_holds_copy(self, reservation):
        return self.session.scalar(
            select(PhysicalCopy)
            .where(PhysicalCopy.id == reservation.allocated_copy_id)
            .with_for_update()
        )

    def fetch_allocate_waiting_reservations_copies(self, item_id):
        return self.session.scalars(
            select(PhysicalCopy)
            .join(CatalogItem, CatalogItem.id == PhysicalCopy.item_id)
            .where(PhysicalCopy.item_id == item_id, PhysicalCopy.status == CopyStatus.AVAILABLE,
                   ((PhysicalCopy.can_rent.is_(True) & CatalogItem.can_rent.is_(True)) |
                    (PhysicalCopy.can_sell.is_(True) & CatalogItem.can_sell.is_(True))))
            .order_by(PhysicalCopy.id)
            .with_for_update()
        )

    def fetch_allocate_waiting_reservations_reservations(self, item_id):
        return self.session.scalars(
            select(Reservation)
            .where(Reservation.item_id == item_id, Reservation.state == ReservationState.WAITING)
            .order_by(Reservation.created_at, Reservation.id)
            .with_for_update()
        )

    def has_waiting(self, item_id):
        return self.session.scalar(select(Reservation.id).where(
            Reservation.item_id == item_id, Reservation.state == ReservationState.WAITING
        ).limit(1)) is not None

    def released_waiting_for_copies(self, copy_ids, today):
        return self.session.scalars(
            select(Reservation.item_id)
            .join(PhysicalCopy, PhysicalCopy.item_id == Reservation.item_id)
            .join(CatalogItem, CatalogItem.id == Reservation.item_id)
            .where(PhysicalCopy.id.in_(copy_ids), Reservation.state == ReservationState.WAITING,
                   CatalogItem.archived.is_(False),
                   CatalogItem.release_date.is_(None) | (CatalogItem.release_date <= today))
            .distinct().order_by(Reservation.item_id)
        ).all()

    def expired_items_for_copies(self, copy_ids, now):
        return self.session.scalars(select(Reservation.item_id).where(
            Reservation.allocated_copy_id.in_(copy_ids), Reservation.state == ReservationState.HELD,
            Reservation.hold_until <= now,
        ).distinct().order_by(Reservation.item_id)).all()

    def released_waiting_item_ids(self, today):
        return self.session.scalars(
            select(Reservation.item_id).join(CatalogItem, CatalogItem.id == Reservation.item_id)
            .where(Reservation.state == ReservationState.WAITING,
                   (CatalogItem.release_date.is_(None) | (CatalogItem.release_date <= today)))
            .distinct()
        ).all()

    def held_for_customer(self, copy_id, customer_id, now, lock=False):
        statement = select(Reservation).where(
            Reservation.allocated_copy_id == copy_id,
            Reservation.customer_id == customer_id,
            Reservation.state == ReservationState.HELD,
            Reservation.hold_until > now,
        )
        if lock:
            statement = statement.with_for_update()
        return self.session.scalar(statement)

    def add_reservation(self, value):
        self.session.add(value)

    def flush(self):
        self.session.flush()

    def get_customer(self, identifier):
        return self.session.get(Customer, identifier)
