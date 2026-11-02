from __future__ import annotations

from decimal import Decimal

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.orm import joinedload

from normastore.application.contracts import (
    CatalogFilters,
    CatalogRow,
    PagedResult,
    PageRequest,
    SortSpec,
)
from normastore.domain.enums import (
    CopyStatus,
    ItemType,
    LineAction,
)
from normastore.infrastructure.database.models import (
    CatalogItem,
    ExternalReview,
    Genre,
    ItemGenre,
    PhysicalCopy,
    Season,
    Show,
)


class CatalogQueries:
    def __init__(self, session):
        self.session = session

    def checkout_copy(self, item_id, action, excluded_copy_ids):
        allowed = (
            PhysicalCopy.can_rent.is_(True)
            if action == LineAction.RENT
            else PhysicalCopy.can_sell.is_(True)
        )
        item_allowed = (
            CatalogItem.can_rent.is_(True)
            if action == LineAction.RENT
            else CatalogItem.can_sell.is_(True)
        )
        statement = (
            select(PhysicalCopy, CatalogItem)
            .join(CatalogItem)
            .where(
                CatalogItem.id == item_id,
                CatalogItem.archived.is_(False),
                item_allowed,
                PhysicalCopy.status == CopyStatus.AVAILABLE,
                allowed,
            )
            .order_by(PhysicalCopy.barcode)
            .limit(1)
        )
        if excluded_copy_ids:
            statement = statement.where(PhysicalCopy.id.not_in(excluded_copy_ids))
        return self.session.execute(statement).one_or_none()

    def reviews(self, item_id, show_id):
        review_filter = ExternalReview.item_id == item_id
        if show_id:
            review_filter = review_filter | (ExternalReview.show_id == show_id)
        return self.session.scalars(
            select(ExternalReview)
            .where(review_filter)
            .order_by(ExternalReview.published_at.desc(), ExternalReview.id.desc())
            .limit(5)
        )

    def show_episode_rows(self, show_id, season_number):
        rentable = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            PhysicalCopy.status == CopyStatus.AVAILABLE,
                            PhysicalCopy.can_rent.is_(True),
                            CatalogItem.can_rent.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        sellable = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            PhysicalCopy.status == CopyStatus.AVAILABLE,
                            PhysicalCopy.can_sell.is_(True),
                            CatalogItem.can_sell.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        )
        statement = (
            select(CatalogItem, Season.season_number, rentable, sellable)
            .join(Season, CatalogItem.season_id == Season.id)
            .outerjoin(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
            .where(CatalogItem.show_id == show_id, CatalogItem.archived.is_(False))
            .group_by(CatalogItem.id, Season.season_number)
            .order_by(Season.season_number, CatalogItem.episode_number, CatalogItem.id)
        )
        if season_number is not None:
            statement = statement.where(Season.season_number == season_number)
        return self.session.execute(statement).all()

    def _catalog_statement(self, filters: CatalogFilters):
        rentable = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            PhysicalCopy.status == CopyStatus.AVAILABLE,
                            PhysicalCopy.can_rent.is_(True),
                            CatalogItem.can_rent.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("rentable_copies")
        sellable = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            PhysicalCopy.status == CopyStatus.AVAILABLE,
                            PhysicalCopy.can_sell.is_(True),
                            CatalogItem.can_sell.is_(True),
                        ),
                        1,
                    ),
                    else_=0,
                )
            ),
            0,
        ).label("sellable_copies")
        total = func.count(PhysicalCopy.id).label("total_copies")
        stmt = (
            select(CatalogItem, total, rentable, sellable)
            .outerjoin(PhysicalCopy)
            .where(CatalogItem.archived.is_(False))
            .group_by(CatalogItem.id)
        )
        if filters.text.strip():
            term = f"%{filters.text.strip()}%"
            stmt = stmt.where(or_(CatalogItem.title.like(term), CatalogItem.overview.like(term)))
        if filters.item_type:
            stmt = stmt.where(CatalogItem.item_type == ItemType(filters.item_type))
        if filters.genre_id:
            stmt = stmt.where(
                select(ItemGenre.item_id)
                .where(
                    ItemGenre.item_id == CatalogItem.id,
                    ItemGenre.genre_id == filters.genre_id,
                )
                .exists()
            )
        if filters.year_from:
            stmt = stmt.where(func.year(CatalogItem.release_date) >= filters.year_from)
        if filters.year_to:
            stmt = stmt.where(func.year(CatalogItem.release_date) <= filters.year_to)
        if filters.rating_min is not None:
            stmt = stmt.where(CatalogItem.vote_average >= filters.rating_min)
        if filters.rental_price_min is not None:
            stmt = stmt.where(CatalogItem.rental_price >= filters.rental_price_min)
        if filters.rental_price_max is not None:
            stmt = stmt.where(CatalogItem.rental_price <= filters.rental_price_max)
        if filters.sale_price_min is not None:
            stmt = stmt.where(CatalogItem.sale_price >= filters.sale_price_min)
        if filters.sale_price_max is not None:
            stmt = stmt.where(CatalogItem.sale_price <= filters.sale_price_max)
        if filters.show_id:
            stmt = stmt.where(CatalogItem.show_id == filters.show_id)
        if filters.season_number is not None:
            stmt = stmt.join(Season, CatalogItem.season_id == Season.id).where(
                Season.season_number == filters.season_number
            )

        copy_filters = []
        if filters.media_format:
            copy_filters.append(PhysicalCopy.media_format == filters.media_format)
        if filters.condition:
            copy_filters.append(PhysicalCopy.condition == filters.condition)
        if filters.copy_status:
            copy_filters.append(PhysicalCopy.status == filters.copy_status)
        if copy_filters:
            matching_copy = (
                select(PhysicalCopy.id)
                .where(PhysicalCopy.item_id == CatalogItem.id, *copy_filters)
                .correlate(CatalogItem)
                .exists()
            )
            stmt = stmt.where(matching_copy)
        if filters.require_rentable:
            stmt = stmt.having(rentable > 0)
        if filters.require_sellable:
            stmt = stmt.having(sellable > 0)
        if filters.item_rentable:
            stmt = stmt.where(CatalogItem.can_rent.is_(True))
        return stmt, total, rentable, sellable

    def query_catalog(
        self,
        filters: CatalogFilters | None = None,
        page_request: PageRequest = PageRequest(page_size=48),
        sort: SortSpec = SortSpec(),
    ) -> PagedResult[CatalogRow]:
        filters = filters or CatalogFilters()
        stmt, total, rentable, sellable = self._catalog_statement(filters)
        sort_fields = {
            "title": CatalogItem.title,
            "type": CatalogItem.item_type,
            "rating": CatalogItem.vote_average,
            "rental_price": CatalogItem.rental_price,
            "sale_price": CatalogItem.sale_price,
            "total_copies": total,
            "rentable_copies": rentable,
            "sellable_copies": sellable,
            "release_date": CatalogItem.release_date,
        }
        expression = sort_fields.get(sort.field, CatalogItem.title)
        ordering = desc(expression) if sort.descending else expression.asc()
        total_items = int(
            self.session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery()))
            or 0
        )
        page_size = max(1, min(page_request.page_size, 200))
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = min(max(1, page_request.page), total_pages)
        rows = self.session.execute(
            stmt.order_by(ordering, CatalogItem.id).offset((page - 1) * page_size).limit(page_size)
        ).all()
        return PagedResult(
            items=tuple(
                CatalogRow(
                    item_id=item.id,
                    item_type=item.item_type,
                    title=item.title,
                    overview=item.overview,
                    release_date=item.release_date,
                    vote_average=item.vote_average,
                    poster_path=item.poster_path,
                    rental_price=Decimal(item.rental_price),
                    sale_price=Decimal(item.sale_price),
                    total_copies=int(copies or 0),
                    rentable_copies=int(rent_count or 0),
                    sellable_copies=int(sell_count or 0),
                )
                for item, copies, rent_count, sell_count in rows
            ),
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )

    def list_catalog(
        self,
        text: str = "",
        item_type: str = "",
        available_only: bool = False,
        page: int = 1,
        page_size: int = 48,
    ):
        """Compatibility wrapper for callers that still need ORM catalog rows."""
        filters = CatalogFilters(text=text, item_type=item_type, require_rentable=available_only)
        stmt, total, rentable, sellable = self._catalog_statement(filters)
        rows = self.session.execute(
            stmt.order_by(CatalogItem.title, CatalogItem.id)
            .offset((max(1, page) - 1) * page_size)
            .limit(page_size)
        ).all()
        return [tuple(row) for row in rows]

    def fetch_list_genres_rows(self):
        return self.session.scalars(select(Genre).order_by(Genre.name))

    def fetch_catalog_item_item(self, item_id):
        return self.session.scalar(
            select(CatalogItem)
            .options(joinedload(CatalogItem.copies), joinedload(CatalogItem.show))
            .where(CatalogItem.id == item_id)
        )

    def fetch_catalog_metadata_genres(self, item):
        return self.session.scalars(
            select(Genre.name)
            .join(ItemGenre, ItemGenre.genre_id == Genre.id)
            .where(ItemGenre.item_id == item.id)
            .order_by(Genre.name)
        )

    def fetch_list_shows_rows(self):
        return self.session.execute(
            select(Show, func.count(Season.id))
            .outerjoin(Season, Season.show_id == Show.id)
            .where(Show.archived.is_(False))
            .group_by(Show.id)
            .order_by(Show.title)
        )

    def fetch_add_episodes_bulk_season(self, season_number, show_id):
        return self.session.scalar(
            select(Season).where(Season.show_id == show_id, Season.season_number == season_number)
        )

    def fetch_add_episodes_bulk_existing_numbers(self, season, show_id):
        return self.session.scalars(
            select(CatalogItem.episode_number).where(
                CatalogItem.show_id == show_id, CatalogItem.season_id == season.id
            )
        )

    def add_audit_log(self, value):
        self.session.add(value)

    def add_catalog_item(self, value):
        self.session.add(value)

    def add_season(self, value):
        self.session.add(value)

    def add_show(self, value):
        self.session.add(value)

    def flush(self):
        self.session.flush()

    def get_show(self, identifier):
        return self.session.get(Show, identifier)
