from sqlalchemy import func, select
from sqlalchemy.orm import Session

from normastore.infrastructure.database.models import CatalogItem, Combo, ComboItem, Show, Voucher


class PromotionsRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def voucher_exists(self, code: str) -> bool:
        return self.session.scalar(select(Voucher.id).where(Voucher.code == code)) is not None

    def vouchers(self, include_inactive: bool):
        statement = select(Voucher)
        if not include_inactive:
            statement = statement.where(Voucher.active.is_(True))
        return self.session.scalars(statement.order_by(Voucher.code)).all()

    def active_voucher(self, code: str):
        return self.session.scalar(
            select(Voucher).where(Voucher.code == code, Voucher.active.is_(True))
        )

    def available_item_ids(self, item_ids: list[int]):
        return self.session.scalars(
            select(CatalogItem.id).where(
                CatalogItem.id.in_(item_ids), CatalogItem.archived.is_(False)
            )
        ).all()

    def show(self, show_id: int):
        return self.session.get(Show, show_id)

    def save_voucher(self, voucher: Voucher) -> None:
        self.session.add(voucher)
        self.session.flush()

    def save_combo(self, combo: Combo, item_ids=()) -> None:
        self.session.add(combo)
        self.session.flush()
        self.session.add_all(ComboItem(combo_id=combo.id, item_id=item_id) for item_id in item_ids)

    def combo_rows(self, include_inactive: bool):
        counts = (
            select(
                ComboItem.combo_id.label("combo_id"),
                func.count(ComboItem.item_id).label("item_count"),
            )
            .group_by(ComboItem.combo_id)
            .subquery()
        )
        statement = (
            select(Combo, Show.title, func.coalesce(counts.c.item_count, 0))
            .outerjoin(Show, Combo.show_id == Show.id)
            .outerjoin(counts, counts.c.combo_id == Combo.id)
            .order_by(Combo.name)
        )
        if not include_inactive:
            statement = statement.where(Combo.active.is_(True))
        return self.session.execute(statement).all()

    def active_combos(self, combo_ids):
        return self.session.scalars(
            select(Combo).where(Combo.id.in_(combo_ids), Combo.active.is_(True))
        )

    def combo_item_ids(self, combo_id: int):
        return self.session.scalars(select(ComboItem.item_id).where(ComboItem.combo_id == combo_id))
