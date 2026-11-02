from __future__ import annotations

from sqlalchemy import func, select

from normastore.domain.enums import CopyStatus, RentalState, ReservationState
from normastore.infrastructure.database.models import (
    PaymentTransaction,
    PhysicalCopy,
    RentalTerm,
    Reservation,
)


class DashboardQueries:
    def __init__(self, session):
        self.session = session

    def fetch_dashboard_rented(self):
        return self.session.scalar(
            select(func.count(PhysicalCopy.id)).where(PhysicalCopy.status == CopyStatus.RENTED)
        )

    def fetch_dashboard_available(self):
        return self.session.scalar(
            select(func.count(PhysicalCopy.id)).where(PhysicalCopy.status == CopyStatus.AVAILABLE)
        )

    def fetch_dashboard_overdue(self, today):
        return self.session.scalar(
            select(func.count(RentalTerm.id)).where(
                RentalTerm.state == RentalState.ACTIVE, RentalTerm.due_date < today
            )
        )

    def fetch_dashboard_held(self):
        return self.session.scalar(
            select(func.count(Reservation.id)).where(
                Reservation.state.in_([ReservationState.WAITING, ReservationState.HELD])
            )
        )

    def fetch_dashboard_cash_flow(self):
        return self.session.scalar(select(func.coalesce(func.sum(PaymentTransaction.amount), 0)))
