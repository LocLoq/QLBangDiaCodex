from __future__ import annotations

from sqlalchemy import case, desc, or_, select

from normastore.application.contracts import (
    InventoryCopy,
    InventoryEpisode,
    InventoryGroup,
    PagedResult,
    PageRequest,
    SortSpec,
)
from normastore.domain.enums import (
    CopyStatus,
    CopyCondition,
)
from normastore.infrastructure.database.models import (
    CatalogItem,
    DepositDefault,
    PhysicalCopy,
    Season,
    Show,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class InventoryQueries:
    def __init__(self, session):
        self.session = session

    def _conditions(self, status, text, condition, media, rentable, sellable):
        conditions = [CatalogItem.archived.is_(False)]
        if status:
            conditions.append(PhysicalCopy.status == status)
        if condition:
            conditions.append(PhysicalCopy.condition == condition)
        if media:
            conditions.append(PhysicalCopy.media_format == media)
        if rentable:
            conditions.extend([CatalogItem.can_rent.is_(True), PhysicalCopy.can_rent.is_(True)])
        if sellable:
            conditions.extend([CatalogItem.can_sell.is_(True), PhysicalCopy.can_sell.is_(True)])
        if text.strip():
            term = f"%{text.strip()}%"
            conditions.append(or_(CatalogItem.title.ilike(term), Show.title.ilike(term), PhysicalCopy.barcode.ilike(term)))
        return conditions

    def query_groups(self, status, text, condition, media, rentable, sellable, page_request, descending=False, item_id=None):
        is_show = case((CatalogItem.show_id.is_not(None), 1), else_=0)
        group_id = case((CatalogItem.show_id.is_not(None), CatalogItem.show_id), else_=CatalogItem.id)
        title = case((CatalogItem.show_id.is_not(None), Show.title), else_=CatalogItem.title)
        statement = (select(is_show.label("is_show"), group_id.label("group_id"), title.label("title"))
                     .select_from(CatalogItem).outerjoin(Show, Show.id == CatalogItem.show_id)
                     .outerjoin(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
                     .where(*self._conditions(status, text, condition, media, rentable, sellable))
                     .group_by(is_show, group_id, title)
                     .order_by(title.desc() if descending else title.asc(), is_show, group_id))
        if item_id is not None:
            statement = statement.where(CatalogItem.id == item_id)
        page = page_rows(self.session, statement, page_request)
        return PagedResult(tuple(InventoryGroup(int(group_id), title, bool(is_show)) for is_show, group_id, title in page.items), page.page, page.page_size, page.total_items, page.total_pages)

    def group_episodes(self, show_id, status, text, condition, media, rentable, sellable, item_id=None):
        statement = (select(CatalogItem.id, CatalogItem.title, Season.season_number, CatalogItem.episode_number)
                     .join(Show, Show.id == CatalogItem.show_id)
                     .join(Season, Season.id == CatalogItem.season_id)
                     .outerjoin(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
                     .where(CatalogItem.show_id == show_id, *self._conditions(status, text, condition, media, rentable, sellable))
                     .distinct().order_by(Season.season_number, CatalogItem.episode_number, CatalogItem.id))
        if item_id is not None:
            statement = statement.where(CatalogItem.id == item_id)
        return [InventoryEpisode(item_id, title, season, episode or 0) for item_id, title, season, episode in self.session.execute(statement)]

    def query_inventory(
        self,
        status: CopyStatus | None = None,
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("title"),
        text: str = "",
        item_id: int | None = None,
        condition: CopyCondition | None = None,
        media: str = "",
        rentable: bool = False,
        sellable: bool = False,
    ) -> PagedResult[InventoryCopy]:
        stmt = (select(PhysicalCopy, CatalogItem).join(CatalogItem)
                .outerjoin(Show, Show.id == CatalogItem.show_id)
                .where(*self._conditions(status, text, condition, media, rentable, sellable)))
        if item_id is not None:
            stmt = stmt.where(CatalogItem.id == item_id)
        fields = {
            "title": CatalogItem.title,
            "barcode": PhysicalCopy.barcode,
            "format": PhysicalCopy.media_format,
            "condition": PhysicalCopy.condition,
            "status": PhysicalCopy.status,
            "rent": PhysicalCopy.can_rent,
            "sell": PhysicalCopy.can_sell,
            "buy": PhysicalCopy.can_sell,
        }
        expression = fields.get(sort.field, CatalogItem.title)
        stmt = stmt.order_by(
            desc(expression) if sort.descending else expression.asc(), PhysicalCopy.id
        )
        page = page_rows(self.session, stmt, page_request)
        return PagedResult(
            tuple(
                InventoryCopy(
                    copy.id,
                    copy.barcode,
                    item.title,
                    copy.media_format,
                    copy.condition,
                    copy.status,
                    copy.can_rent,
                    copy.can_sell,
                    copy.rental_price_override,
                    copy.sale_price_override,
                    copy.condition_percent,
                    copy.rental_price_mode,
                    copy.sale_price_mode,
                    copy.rental_price_percent,
                    copy.sale_price_percent,
                )
                for copy, item in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )

    def fetch_add_copy_check(self, barcode):
        return self.session.scalar(select(PhysicalCopy).where(PhysicalCopy.barcode == barcode))

    def deposit_defaults(self):
        return self.session.scalars(select(DepositDefault))



    def lock_copy(self, copy_id):
        return self.session.scalar(
            select(PhysicalCopy).where(PhysicalCopy.id == copy_id).with_for_update()
        )

    def fetch_update_inventory_copy_check(self, copy_id, request):
        return self.session.scalar(
            select(PhysicalCopy.id).where(
                PhysicalCopy.barcode == request.barcode.strip(), PhysicalCopy.id != copy_id
            )
        )

    def fetch_archive_items_items(self, item_ids):
        return self.session.scalars(select(CatalogItem).where(CatalogItem.id.in_(item_ids)))

    def fetch_bulk_update_catalog_prices_items(self, item_ids):
        return self.session.scalars(
            select(CatalogItem).where(
                CatalogItem.id.in_(set(item_ids)),
                CatalogItem.archived.is_(False),
                CatalogItem.can_rent.is_(True),
            )
        )


    def add_audit_log(self, value):
        self.session.add(value)

    def add_copy_status_history(self, value):
        self.session.add(value)

    def add_deposit_default(self, value):
        self.session.add(value)

    def add_physical_copy(self, value):
        self.session.add(value)

    def flush(self):
        self.session.flush()
