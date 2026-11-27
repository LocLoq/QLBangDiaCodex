from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import and_, case, func, select

from normastore.domain.enums import CopyStatus, LineAction, RentalState, ReservationState
from normastore.infrastructure.database.models import (
    PaymentTransaction,
    CatalogItem,
    Order,
    OrderLine,
    PhysicalCopy,
    RentalTerm,
    Reservation,
    Show,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


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

    def fetch_dashboard_cash_flow(self, today):
        local_midnight = datetime.combine(today, time.min, ZoneInfo("Asia/Ho_Chi_Minh"))
        start = local_midnight.astimezone(timezone.utc).replace(tzinfo=None)
        end = (local_midnight + timedelta(days=1)).astimezone(timezone.utc).replace(tzinfo=None)
        return self.session.scalar(select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
            PaymentTransaction.created_at >= start, PaymentTransaction.created_at < end
        ))

    def _low_stock_statement(self):
        rentable = func.sum(case((and_(PhysicalCopy.status == CopyStatus.AVAILABLE, PhysicalCopy.can_rent.is_(True), CatalogItem.can_rent.is_(True)), 1), else_=0))
        sellable = func.sum(case((and_(PhysicalCopy.status == CopyStatus.AVAILABLE, PhysicalCopy.can_sell.is_(True), CatalogItem.can_sell.is_(True)), 1), else_=0))
        lowest = func.least(case((CatalogItem.can_rent.is_(True), rentable), else_=3),
                            case((CatalogItem.can_sell.is_(True), sellable), else_=3))
        return (select(CatalogItem.id, CatalogItem.title, rentable, sellable)
            .outerjoin(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
            .where(CatalogItem.archived.is_(False),
                   CatalogItem.release_date.is_(None) | (CatalogItem.release_date <= date.today()))
            .group_by(CatalogItem.id, CatalogItem.title, CatalogItem.can_rent, CatalogItem.can_sell)
            .having((CatalogItem.can_rent.is_(True) & (rentable <= 2)) | (CatalogItem.can_sell.is_(True) & (sellable <= 2)))
            .order_by(lowest, CatalogItem.title, CatalogItem.id))

    def low_stock(self, limit=100):
        return self.session.execute(self._low_stock_statement().limit(limit)).all()

    def low_stock_page(self, page_request):
        return page_rows(self.session, self._low_stock_statement(), page_request)

    def popular(self, action, since, limit=20):
        title = func.coalesce(Show.title, CatalogItem.title)
        group_key = func.coalesce(Show.id, -CatalogItem.id)
        count = func.count(OrderLine.id)
        return self.session.execute(
            select(title, count).select_from(OrderLine)
            .join(Order, Order.id == OrderLine.order_id)
            .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
            .join(CatalogItem, CatalogItem.id == PhysicalCopy.item_id)
            .outerjoin(Show, Show.id == CatalogItem.show_id)
            .where(OrderLine.action == action, Order.created_at >= since)
            .group_by(group_key, title).order_by(count.desc(), title).limit(limit)
        ).all()

    def popular_targets(self, action, since, limit=20):
        title = func.coalesce(Show.title, CatalogItem.title)
        count = func.count(OrderLine.id)
        return self.session.execute(
            select(Show.id, case((Show.id.is_(None), CatalogItem.id), else_=None), title, count)
            .select_from(OrderLine).join(Order, Order.id == OrderLine.order_id)
            .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
            .join(CatalogItem, CatalogItem.id == PhysicalCopy.item_id)
            .outerjoin(Show, Show.id == CatalogItem.show_id)
            .where(OrderLine.action == action, Order.created_at >= since)
            .group_by(Show.id, case((Show.id.is_(None), CatalogItem.id), else_=None), title)
            .order_by(count.desc(), title).limit(limit)
        ).all()

    def _upcoming_statement(self, today):
        return (select(CatalogItem.id, CatalogItem.title, CatalogItem.release_date)
            .where(CatalogItem.archived.is_(False), CatalogItem.release_date > today,
                   CatalogItem.can_rent.is_(True) | CatalogItem.can_sell.is_(True))
            .order_by(CatalogItem.release_date, CatalogItem.title, CatalogItem.id))

    def upcoming(self, today, limit=100):
        return self.session.execute(self._upcoming_statement(today).limit(limit)).all()

    def upcoming_page(self, today, page_request):
        return page_rows(self.session, self._upcoming_statement(today), page_request)

    def discovery(self, today, since, limit=50):
        recent_counts = (select(PhysicalCopy.item_id.label("item_id"), func.count(OrderLine.id).label("count"))
                         .select_from(OrderLine).join(Order, Order.id == OrderLine.order_id)
                         .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
                         .where(Order.created_at >= since, OrderLine.action.in_((LineAction.RENT, LineAction.BUY)))
                         .group_by(PhysicalCopy.item_id).subquery())
        available = select(PhysicalCopy.id).where(
            PhysicalCopy.item_id == CatalogItem.id,
            PhysicalCopy.status == CopyStatus.AVAILABLE,
            ((PhysicalCopy.can_rent.is_(True) & CatalogItem.can_rent.is_(True)) |
             (PhysicalCopy.can_sell.is_(True) & CatalogItem.can_sell.is_(True))),
        ).exists()
        return self.session.execute(
            select(CatalogItem.id, CatalogItem.title, func.coalesce(recent_counts.c.count, 0),
                   CatalogItem.discovery_discount_active, CatalogItem.discovery_discount_percent,
                   CatalogItem.discovery_discount_starts, CatalogItem.discovery_discount_ends)
            .outerjoin(recent_counts, recent_counts.c.item_id == CatalogItem.id)
            .where(CatalogItem.archived.is_(False), available,
                   CatalogItem.release_date.is_(None) | (CatalogItem.release_date <= today))
            .order_by(func.coalesce(recent_counts.c.count, 0), CatalogItem.title, CatalogItem.id)
            .limit(limit)
        ).all()

    def random_items(self, today, limit=8):
        available = select(PhysicalCopy.id).where(
            PhysicalCopy.item_id == CatalogItem.id, PhysicalCopy.status == CopyStatus.AVAILABLE,
            ((PhysicalCopy.can_rent.is_(True) & CatalogItem.can_rent.is_(True)) |
             (PhysicalCopy.can_sell.is_(True) & CatalogItem.can_sell.is_(True))),
        ).exists()
        return self.session.execute(
            select(CatalogItem.id, CatalogItem.title).where(
                CatalogItem.archived.is_(False), available,
                CatalogItem.release_date.is_(None) | (CatalogItem.release_date <= today)
            ).order_by(func.rand()).limit(limit)
        ).all()
