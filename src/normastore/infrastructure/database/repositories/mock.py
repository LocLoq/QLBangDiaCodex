from __future__ import annotations

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import joinedload

from normastore.domain.enums import CopyStatus, ItemType, RentalState
from normastore.infrastructure.database.models import (
    CatalogItem,
    Combo,
    ComboItem,
    Customer,
    MockDailyRun,
    Order,
    OrderLine,
    PaymentTransaction,
    PhysicalCopy,
    PremiumMembership,
    RentalTerm,
    Voucher,
)


class MockQueries:
    def __init__(self, session):
        self.session = session

    def fetch_ensure_mock_fixtures_item_ids(self):
        return self.session.scalars(
            select(CatalogItem.id)
            .join(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
            .where(
                CatalogItem.archived.is_(False),
                CatalogItem.can_rent.is_(True),
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                PhysicalCopy.can_rent.is_(True),
            )
            .distinct()
            .order_by(CatalogItem.id)
            .limit(20)
        )

    def fetch_ensure_mock_fixtures_show_ids(self):
        return self.session.scalars(
            select(CatalogItem.show_id)
            .join(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
            .where(
                CatalogItem.item_type == ItemType.EPISODE,
                CatalogItem.show_id.is_not(None),
                CatalogItem.archived.is_(False),
                CatalogItem.can_rent.is_(True),
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                PhysicalCopy.can_rent.is_(True),
            )
            .group_by(CatalogItem.show_id)
            .having(func.count(func.distinct(CatalogItem.id)) >= 2)
            .order_by(CatalogItem.show_id)
            .limit(10)
        )

    def combo_by_name(self, name):
        return self.session.scalar(select(Combo.id).where(Combo.name == name))


    def voucher_by_code(self, code):
        return self.session.scalar(select(Voucher.id).where(Voucher.code == code))

    def customers(self):
        return self.session.scalars(select(Customer).order_by(Customer.id))

    def premium_member_ids(self):
        return self.session.scalars(select(PremiumMembership.customer_id))

    def fetch_ensure_mock_fixtures_active(self, today):
        return self.session.scalars(
            select(PremiumMembership.customer_id).where(
                PremiumMembership.starts_on <= today, PremiumMembership.ends_on >= today
            )
        )

    def fetch_ensure_mock_fixtures_expired(self, today):
        return self.session.scalars(
            select(PremiumMembership.customer_id).where(PremiumMembership.ends_on < today)
        )

    def fetch_seed_mock_day_check(self, business_date):
        return self.session.scalar(
            select(MockDailyRun.id).where(MockDailyRun.business_date == business_date)
        )


    def fetch_seed_mock_day_available(self, volume_per_day):
        return self.session.scalars(
            select(PhysicalCopy)
            .join(PhysicalCopy.item)
            .options(joinedload(PhysicalCopy.item))
            .where(
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                or_(
                    and_(PhysicalCopy.can_rent.is_(True), CatalogItem.can_rent.is_(True)),
                    and_(PhysicalCopy.can_sell.is_(True), CatalogItem.can_sell.is_(True)),
                ),
            )
            .order_by(PhysicalCopy.id)
            .limit(volume_per_day * 4)
        )

    def fetch_seed_mock_day_combos(self):
        return self.session.scalars(
            select(Combo).where(Combo.name.like("MOCK-COMBO-%"), Combo.active.is_(True))
        )

    def fetch_seed_mock_day_active_vouchers(self, today):
        return self.session.scalars(
            select(Voucher.code)
            .where(
                Voucher.code.like("MOCKV%"),
                Voucher.active.is_(True),
                or_(Voucher.starts_on.is_(None), Voucher.starts_on <= today),
                or_(Voucher.ends_on.is_(None), Voucher.ends_on >= today),
            )
            .order_by(Voucher.code)
        )

    def fetch_seed_mock_day_premium_ids(self, business_date):
        return self.session.scalars(
            select(PremiumMembership.customer_id).where(
                PremiumMembership.starts_on <= business_date,
                PremiumMembership.ends_on >= business_date,
            )
        )

    def payments_for_order(self, order):
        return self.session.scalars(
            select(PaymentTransaction).where(PaymentTransaction.order_id == order.id)
        )

    def fetch_seed_mock_day_open_counts(self):
        return self.session.execute(
            select(Order.customer_id, func.count(RentalTerm.id))
            .join(OrderLine, OrderLine.order_id == Order.id)
            .join(RentalTerm, RentalTerm.line_id == OrderLine.id)
            .where(RentalTerm.state == RentalState.ACTIVE)
            .group_by(Order.customer_id)
        )

    def fetch_seed_mock_day_rows_2(self, combo):
        return self.session.scalars(select(ComboItem.item_id).where(ComboItem.combo_id == combo.id))

    def rentals_for_order(self, order):
        return self.session.scalars(
            select(RentalTerm).join(OrderLine).where(OrderLine.order_id == order.id)
        )

    def fetch_ensure_mock_fixtures_customers_2(self):
        return self.session.scalars(select(Customer).order_by(Customer.id).limit(450))



    def fetch_ensure_mock_fixtures_item_ids_2(self):
        return self.session.scalars(
            select(CatalogItem.id)
            .where(CatalogItem.archived.is_(False))
            .order_by(CatalogItem.id)
            .limit(40)
        )

    def fetch_ensure_mock_fixtures_existing(self):
        return self.session.scalar(select(func.count(Combo.id)))


    def daily_run(self, cursor):
        return self.session.scalar(
            select(MockDailyRun.id).where(MockDailyRun.business_date == cursor)
        )

    def fetch_seed_mock_range_legacy_available(self, volume_per_day):
        return self.session.scalars(
            select(PhysicalCopy)
            .options(joinedload(PhysicalCopy.item))
            .where(PhysicalCopy.status == CopyStatus.AVAILABLE)
            .order_by(PhysicalCopy.id)
            .limit(volume_per_day * 4)
        )




    def add_combo(self, value):
        self.session.add(value)

    def add_combo_item_batch(self, values):
        self.session.add_all(values)

    def add_mock_daily_run(self, value):
        self.session.add(value)

    def add_payment_transaction(self, value):
        self.session.add(value)

    def add_premium_membership(self, value):
        self.session.add(value)

    def add_return_line(self, value):
        self.session.add(value)

    def add_return_receipt(self, value):
        self.session.add(value)

    def add_voucher(self, value):
        self.session.add(value)

    def flush(self):
        self.session.flush()

    def get_physical_copy(self, identifier):
        return self.session.get(PhysicalCopy, identifier)
