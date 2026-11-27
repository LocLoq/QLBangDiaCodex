from __future__ import annotations

from decimal import Decimal
from datetime import date, datetime, timezone

from sqlalchemy import and_, case, desc, func, or_, select
from sqlalchemy.orm import joinedload, selectinload

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
    ReservationState,
)
from normastore.infrastructure.database.models import (
    CatalogItem,
    ExternalReview,
    Genre,
    ItemGenre,
    PhysicalCopy,
    Reservation,
    Season,
    Show,
)


class CatalogQueries:
    def __init__(self, session):
        self.session = session

    def checkout_copy(self, item_id, action, excluded_copy_ids):
        rows = self.checkout_copies(item_id, action, excluded_copy_ids, limit=1)
        return rows[0] if rows else None

    @staticmethod
    def _checkout_status(customer_id=None):
        allowed_status = PhysicalCopy.status == CopyStatus.AVAILABLE
        if customer_id is not None:
            own_hold = select(Reservation.id).where(
                Reservation.allocated_copy_id == PhysicalCopy.id,
                Reservation.customer_id == customer_id,
                Reservation.state == ReservationState.HELD,
                Reservation.hold_until > datetime.now(timezone.utc),
            ).correlate(PhysicalCopy).exists()
            allowed_status = allowed_status | ((PhysicalCopy.status == CopyStatus.HELD) & own_hold)
        return allowed_status

    def checkout_copies(self, item_id, action, excluded_copy_ids, limit=None, customer_id=None):
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
        allowed_status = self._checkout_status(customer_id)
        statement = (
            select(PhysicalCopy, CatalogItem)
            .join(CatalogItem)
            .where(
                CatalogItem.id == item_id,
                CatalogItem.archived.is_(False),
                (CatalogItem.release_date.is_(None) | (CatalogItem.release_date <= date.today())),
                item_allowed,
                allowed_status,
                allowed,
            )
            .order_by(PhysicalCopy.barcode)
        )
        if excluded_copy_ids:
            statement = statement.where(PhysicalCopy.id.not_in(excluded_copy_ids))
        if limit is not None:
            statement = statement.limit(limit)
        return self.session.execute(statement).all()

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
        released = or_(CatalogItem.release_date.is_(None), CatalogItem.release_date <= date.today())
        rentable = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            PhysicalCopy.status == CopyStatus.AVAILABLE,
                            PhysicalCopy.can_rent.is_(True),
                            CatalogItem.can_rent.is_(True),
                            released,
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
                            released,
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

    def _catalog_statement(self, filters: CatalogFilters, customer_id=None, *, for_checkout=False):
        released = or_(CatalogItem.release_date.is_(None), CatalogItem.release_date <= date.today())
        allowed_status = self._checkout_status(customer_id)
        rentable = func.coalesce(
            func.sum(
                case(
                    (
                        and_(
                            allowed_status,
                            PhysicalCopy.can_rent.is_(True),
                            CatalogItem.can_rent.is_(True),
                            released,
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
                            allowed_status,
                            PhysicalCopy.can_sell.is_(True),
                            CatalogItem.can_sell.is_(True),
                            released,
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
            stmt = stmt.where(or_(CatalogItem.title.like(term), CatalogItem.overview.like(term),
                select(Show.id).where(Show.id == CatalogItem.show_id, Show.title.like(term)).exists()))
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
        if for_checkout and filters.require_rentable and filters.require_sellable:
            stmt = stmt.having(or_(rentable > 0, sellable > 0))
        else:
            if filters.require_rentable:
                stmt = stmt.having(rentable > 0)
            if filters.require_sellable:
                stmt = stmt.having(sellable > 0)
        if filters.item_rentable:
            stmt = stmt.where(CatalogItem.can_rent.is_(True))
        if filters.item_rentable_or_sellable:
            stmt = stmt.where(CatalogItem.can_rent.is_(True) | CatalogItem.can_sell.is_(True))
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
            stmt.options(selectinload(CatalogItem.show), selectinload(CatalogItem.season))
            .order_by(ordering, CatalogItem.id).offset((page - 1) * page_size).limit(page_size)
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
                    poster_path=item.poster_path or (item.show.poster_path if item.show else None),
                    rental_price=Decimal(item.rental_price),
                    sale_price=Decimal(item.sale_price),
                    total_copies=int(copies or 0),
                    rentable_copies=int(rent_count or 0),
                    sellable_copies=int(sell_count or 0),
                    show_id=item.show_id,
                    show_title=item.show.title if item.show else None,
                    season_number=item.season.season_number if item.season else None,
                    episode_number=item.episode_number,
                )
                for item, copies, rent_count, sell_count in rows
            ),
            page=page,
            page_size=page_size,
            total_items=total_items,
            total_pages=total_pages,
        )

    def query_checkout_catalog(self, filters=None, page_request=PageRequest(page_size=48), sort=SortSpec(), customer_id=None):
        items = self._catalog_statement(filters or CatalogFilters(), customer_id, for_checkout=True)[0].subquery()
        is_show = items.c.show_id.is_not(None)
        group_id = case((is_show, items.c.show_id), else_=items.c.id)
        title = func.max(case((is_show, Show.title), else_=items.c.title)).label("title")
        grouped = select(
            func.min(items.c.id).label("item_id"), func.max(items.c.item_type).label("item_type"),
            title, func.max(case((is_show, Show.overview), else_=items.c.overview)).label("overview"),
            func.min(items.c.release_date).label("release_date"),
            func.max(case((is_show, Show.vote_average), else_=items.c.vote_average)).label("vote_average"),
            func.max(case((is_show, Show.poster_path), else_=items.c.poster_path)).label("poster_path"),
            func.min(items.c.rental_price).label("rental_price"), func.min(items.c.sale_price).label("sale_price"),
            func.sum(items.c.total_copies).label("total_copies"),
            func.sum(items.c.rentable_copies).label("rentable_copies"),
            func.sum(items.c.sellable_copies).label("sellable_copies"),
            func.max(items.c.show_id).label("show_id"),
        ).select_from(items.outerjoin(Show, Show.id == items.c.show_id)).group_by(is_show, group_id).subquery()
        total_items = int(self.session.scalar(select(func.count()).select_from(grouped)) or 0)
        page_size = max(1, min(page_request.page_size, 200))
        total_pages = max(1, (total_items + page_size - 1) // page_size)
        page = min(max(1, page_request.page), total_pages)
        fields = {"type": grouped.c.item_type, "rating": grouped.c.vote_average}
        expression = fields.get(sort.field, grouped.c.get(sort.field, grouped.c.title))
        ordering = desc(expression) if sort.descending else expression.asc()
        rows = self.session.execute(select(grouped).order_by(ordering, grouped.c.item_id)
                                    .offset((page - 1) * page_size).limit(page_size)).mappings()
        return PagedResult(items=tuple(CatalogRow(**dict(row)) for row in rows), page=page,
                           page_size=page_size, total_items=total_items, total_pages=total_pages)

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

    def set_item_genres(self, item_id, names):
        genre_ids = set()
        for name in names:
            genre = self.session.scalar(select(Genre).where(Genre.name == name))
            if genre is None:
                genre = Genre(name=name)
                self.session.add(genre)
                self.session.flush()
            genre_ids.add(genre.id)
        current = list(self.session.scalars(select(ItemGenre).where(ItemGenre.item_id == item_id)))
        current_ids = {link.genre_id for link in current}
        for link in current:
            if link.genre_id not in genre_ids:
                self.session.delete(link)
        for genre_id in genre_ids - current_ids:
            self.session.add(ItemGenre(item_id=item_id, genre_id=genre_id))

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

    def show_by_title(self, title):
        return self.session.scalar(select(Show).where(Show.title == title, Show.archived.is_(False)))

    def movie_by_title_date(self, title, release_date):
        return self.session.scalar(select(CatalogItem).where(
            CatalogItem.item_type == ItemType.MOVIE, CatalogItem.title == title,
            CatalogItem.release_date == release_date, CatalogItem.archived.is_(False),
        ))
