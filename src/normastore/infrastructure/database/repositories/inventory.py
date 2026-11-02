from __future__ import annotations

from sqlalchemy import desc, select

from normastore.application.contracts import (
    InventoryCopy,
    PagedResult,
    PageRequest,
    SortSpec,
)
from normastore.domain.enums import (
    CopyStatus,
)
from normastore.infrastructure.database.models import (
    CatalogItem,
    DepositDefault,
    PhysicalCopy,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class InventoryQueries:
    def __init__(self, session):
        self.session = session

    def query_inventory(
        self,
        status: CopyStatus | None = None,
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("title"),
    ) -> PagedResult[InventoryCopy]:
        stmt = select(PhysicalCopy, CatalogItem).join(CatalogItem)
        if status:
            stmt = stmt.where(PhysicalCopy.status == status)
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


    def fetch_apply_deposit_defaults_to_inventory_copies(self):
        return self.session.scalars(select(PhysicalCopy).with_for_update())

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
