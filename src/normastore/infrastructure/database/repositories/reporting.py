from datetime import timedelta

from sqlalchemy import DateTime, case, func, select

from normastore.domain.business_time import utc_start_of_day
from normastore.domain.enums import CopyStatus, LineAction, RentalState, ReservationState
from normastore.infrastructure.database.models import (
    CatalogItem,
    Combo,
    Customer,
    Genre,
    ItemGenre,
    NotificationOutbox,
    Order,
    OrderDiscount,
    OrderLine,
    PaymentTransaction,
    PenaltyCharge,
    PhysicalCopy,
    PremiumMembership,
    RentalExtension,
    RentalTerm,
    Reservation,
    ReturnLine,
    ReturnReceipt,
    SaleReturn,
)


class ReportingRepository:
    def __init__(self, session, start_on=None, end_on=None):
        self.session = session
        self.start_on = start_on
        self.end_on = end_on

    def for_period(self, start_on, end_on):
        return ReportingRepository(self.session, start_on, end_on)

    def _genre_filter(self, genre_id):
        if genre_id is None:
            return []
        return [select(ItemGenre.item_id).where(
            ItemGenre.item_id == PhysicalCopy.item_id, ItemGenre.genre_id == genre_id
        ).exists()]

    def revenue_series(self, action=None, genre_id=None):
        day = func.date(func.convert_tz(Order.created_at, "+00:00", "+07:00"))
        statement = (select(day, OrderLine.action,
                            func.sum(self._net_line_revenue()))
                     .select_from(OrderLine).join(Order, Order.id == OrderLine.order_id)
                     .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
                     .where(OrderLine.action.in_((LineAction.RENT, LineAction.BUY)),
                            *self._period(Order.created_at), *self._genre_filter(genre_id)))
        if action:
            statement = statement.where(OrderLine.action == action)
        return self.session.execute(statement.group_by(day, OrderLine.action).order_by(day)).all()

    def damage_counts(self, action=None, genre_id=None):
        result = []
        if action != LineAction.BUY:
            result.extend(self.session.execute(
                select(ReturnLine.outcome, func.count(ReturnLine.id)).select_from(ReturnLine)
                .join(ReturnReceipt, ReturnReceipt.id == ReturnLine.receipt_id)
                .join(RentalTerm, RentalTerm.id == ReturnLine.rental_term_id)
                .join(OrderLine, OrderLine.id == RentalTerm.line_id)
                .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
                .where(ReturnLine.outcome.in_(("LIGHT_DAMAGE", "HEAVY_DAMAGE", "LOST")),
                       *self._period(ReturnReceipt.returned_on), *self._genre_filter(genre_id))
                .group_by(ReturnLine.outcome)
            ).all())
        if action != LineAction.RENT:
            rows = self.session.execute(
                select(SaleReturn.condition_at_return, func.count(SaleReturn.id)).select_from(SaleReturn)
                .join(OrderLine, OrderLine.id == SaleReturn.sale_line_id)
                .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
                .where(SaleReturn.condition_at_return.in_(("WORN", "DAMAGED")),
                       *self._period(SaleReturn.returned_on), *self._genre_filter(genre_id))
                .group_by(SaleReturn.condition_at_return)
            ).all()
            result.extend((f"SALE_{condition}", count) for condition, count in rows)
        return result

    def genre_sales(self, action=None, genre_id=None):
        if action == LineAction.RENT:
            return []
        statement = (select(Genre.name, func.count(func.distinct(OrderLine.id)))
                     .select_from(OrderLine).join(Order, Order.id == OrderLine.order_id)
                     .join(PhysicalCopy, PhysicalCopy.id == OrderLine.copy_id)
                     .join(ItemGenre, ItemGenre.item_id == PhysicalCopy.item_id)
                     .join(Genre, Genre.id == ItemGenre.genre_id)
                     .where(OrderLine.action == LineAction.BUY, *self._period(Order.created_at)))
        if genre_id is not None:
            statement = statement.where(Genre.id == genre_id)
        return self.session.execute(statement.group_by(Genre.id, Genre.name)
                                    .order_by(func.count(func.distinct(OrderLine.id)).desc(), Genre.name)
                                    .limit(10)).all()

    def _period(self, column):
        conditions = []
        is_timestamp = isinstance(column.type, DateTime)
        if self.start_on:
            conditions.append(column >= (utc_start_of_day(self.start_on) if is_timestamp else self.start_on))
        if self.end_on:
            if is_timestamp:
                conditions.append(column < utc_start_of_day(self.end_on + timedelta(days=1)))
            else:
                conditions.append(column <= self.end_on)
        return conditions

    def line_revenue(self, action):
        return self.session.scalar(
            select(func.coalesce(func.sum(self._net_line_revenue()), 0))
            .join(Order, OrderLine.order_id == Order.id)
            .where(OrderLine.action == action, *self._period(Order.created_at))
        )

    @staticmethod
    def _net_line_revenue():
        legacy_deposit = case(
            ((Order.deposit_applied.is_(None) & OrderLine.source_rental_line_id.is_not(None)), OrderLine.discount_amount),
            else_=0,
        )
        return OrderLine.unit_price - OrderLine.discount_amount + legacy_deposit

    def extension_revenue(self):
        return self.session.scalar(
            select(func.coalesce(func.sum(RentalExtension.fee), 0)).where(
                *self._period(RentalExtension.created_at)
            )
        )

    def premium_revenue(self):
        return self.session.scalar(
            select(func.coalesce(func.sum(PremiumMembership.price_paid), 0)).where(
                *self._period(PremiumMembership.created_at)
            )
        )

    def cash_collected(self):
        return self.session.scalar(
            select(func.coalesce(func.sum(PaymentTransaction.amount), 0)).where(
                PaymentTransaction.amount > 0, *self._period(PaymentTransaction.created_at)
            )
        )

    def cash_refunded(self):
        return self.session.scalar(
            select(func.coalesce(-func.sum(PaymentTransaction.amount), 0)).where(
                PaymentTransaction.amount < 0, *self._period(PaymentTransaction.created_at)
            )
        )

    def order_totals(self):
        legacy_deposit = (select(func.coalesce(func.sum(OrderLine.discount_amount), 0))
                          .where(OrderLine.order_id == Order.id, OrderLine.source_rental_line_id.is_not(None))
                          .correlate(Order).scalar_subquery())
        return self.session.execute(
            select(
                func.coalesce(func.sum(Order.gross_total), 0),
                func.coalesce(func.sum(Order.discount_total - case((Order.deposit_applied.is_(None), legacy_deposit), else_=0)), 0),
            ).where(*self._period(Order.created_at))
        ).one()

    def premium_counts(self, today):
        active = self.session.scalar(
            select(func.count(func.distinct(PremiumMembership.customer_id))).where(
                PremiumMembership.active_on(today)
            )
        )
        expired = self.session.scalar(
            select(func.count(func.distinct(PremiumMembership.customer_id))).where(
                PremiumMembership.ends_on < today, PremiumMembership.cancelled_on.is_(None)
            )
        )
        return active, expired

    def notification_counts(self):
        return self.session.execute(
            select(
                NotificationOutbox.channel,
                NotificationOutbox.status,
                func.count(NotificationOutbox.id),
            )
            .where(*self._period(NotificationOutbox.scheduled_for))
            .group_by(NotificationOutbox.channel, NotificationOutbox.status)
        ).all()

    def penalties(self):
        return self.session.scalar(
            select(func.coalesce(func.sum(PenaltyCharge.amount), 0)).where(
                *self._period(PenaltyCharge.created_at)
            )
        )

    def sale_refunds(self):
        return self.session.scalar(
            select(func.coalesce(func.sum(SaleReturn.refund_amount), 0)).where(
                *self._period(SaleReturn.returned_on)
            )
        )

    def deposits_held(self):
        return self.session.scalar(
            select(func.coalesce(func.sum(OrderLine.deposit_amount), 0))
            .join(RentalTerm, RentalTerm.line_id == OrderLine.id)
            .where(RentalTerm.state == RentalState.ACTIVE)
        )

    def status_counts(self):
        return self.session.execute(
            select(PhysicalCopy.status, func.count(PhysicalCopy.id)).group_by(PhysicalCopy.status)
        ).all()

    def top_titles(self, action: LineAction):
        return self.session.execute(
            select(OrderLine.title_snapshot, func.count(OrderLine.id))
            .join(Order, OrderLine.order_id == Order.id)
            .where(OrderLine.action == action, *self._period(Order.created_at))
            .group_by(OrderLine.title_snapshot)
            .order_by(func.count(OrderLine.id).desc(), OrderLine.title_snapshot)
            .limit(10)
        ).all()

    def top_customers(self):
        total = func.sum(self._net_line_revenue())
        order_count = func.count(func.distinct(Order.id))
        return self.session.execute(
            select(Customer.id, Customer.full_name, Customer.phone, order_count, total)
            .select_from(OrderLine)
            .join(Order, OrderLine.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .where(OrderLine.action.in_((LineAction.RENT, LineAction.BUY, LineAction.PREMIUM)),
                   *self._period(Order.created_at))
            .group_by(Customer.id, Customer.full_name, Customer.phone)
            .order_by(total.desc(), Customer.full_name, Customer.id)
            .limit(10)
        ).all()

    def combo_codes(self):
        return self.session.scalars(
            select(OrderDiscount.source_code)
            .join(Order, OrderDiscount.order_id == Order.id)
            .where(OrderDiscount.source == "COMBO", *self._period(Order.created_at))
        )

    def combo_names(self, combo_ids):
        return self.session.execute(
            select(Combo.id, Combo.name).where(Combo.id.in_(combo_ids))
        ).all()

    def top_vouchers(self):
        return self.session.execute(
            select(OrderDiscount.source_code, func.count(OrderDiscount.id))
            .join(Order, OrderDiscount.order_id == Order.id)
            .where(
                OrderDiscount.source == "VOUCHER",
                OrderDiscount.source_code.is_not(None),
                *self._period(Order.created_at),
            )
            .group_by(OrderDiscount.source_code)
            .order_by(func.count(OrderDiscount.id).desc(), OrderDiscount.source_code)
            .limit(10)
        ).all()

    def discounts_by_source(self):
        return self.session.execute(
            select(OrderDiscount.source, func.coalesce(func.sum(OrderDiscount.amount), 0))
            .join(Order, OrderDiscount.order_id == Order.id)
            .where(*self._period(Order.created_at))
            .group_by(OrderDiscount.source)
            .order_by(func.sum(OrderDiscount.amount).desc())
        ).all()

    def stock_rows(self):
        return self.session.execute(
            select(
                CatalogItem.id,
                CatalogItem.title,
                func.coalesce(
                    func.sum((PhysicalCopy.status == CopyStatus.AVAILABLE) & PhysicalCopy.can_rent),
                    0,
                ),
            )
            .outerjoin(PhysicalCopy)
            .where(CatalogItem.archived.is_(False))
            .group_by(CatalogItem.id)
            .order_by(CatalogItem.title)
        ).all()

    def stock_eta(self, item_ids):
        return self.session.execute(
            select(PhysicalCopy.item_id, func.min(RentalTerm.due_date))
            .join(OrderLine, OrderLine.copy_id == PhysicalCopy.id)
            .join(RentalTerm, RentalTerm.line_id == OrderLine.id)
            .where(PhysicalCopy.item_id.in_(item_ids), RentalTerm.state == RentalState.ACTIVE)
            .group_by(PhysicalCopy.item_id)
        ).all()

    def waiting_reservations(self):
        return self.session.execute(
            select(CatalogItem.title, func.count(Reservation.id))
            .join(CatalogItem, Reservation.item_id == CatalogItem.id)
            .where(Reservation.state == ReservationState.WAITING)
            .group_by(CatalogItem.id)
            .order_by(func.count(Reservation.id).desc(), CatalogItem.title)
            .limit(20)
        ).all()

    def overdue_rows(self, today):
        return self.session.execute(
            select(RentalTerm, Customer)
            .join(OrderLine, RentalTerm.line_id == OrderLine.id)
            .join(Order, OrderLine.order_id == Order.id)
            .join(Customer, Order.customer_id == Customer.id)
            .where(RentalTerm.state == RentalState.ACTIVE, RentalTerm.due_date < today)
        ).all()
