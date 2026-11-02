from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select

from normastore.domain.enums import CopyStatus, LineAction
from normastore.infrastructure.database.models import (
    CatalogItem,
    Order,
    OrderLine,
    PhysicalCopy,
    RecommendationCache,
)


class RecommendationRepository:
    def __init__(self, session):
        self.session = session

    def candidates(self, customer_id: int | None, limit: int) -> list[CatalogItem]:
        available = func.sum((PhysicalCopy.status == CopyStatus.AVAILABLE) & PhysicalCopy.can_rent)
        recent = datetime.now(timezone.utc) - timedelta(days=90)
        trend_rows = (
            select(
                PhysicalCopy.item_id.label("item_id"),
                func.count(OrderLine.id).label("trend"),
            )
            .select_from(PhysicalCopy)
            .join(OrderLine, OrderLine.copy_id == PhysicalCopy.id)
            .join(Order, OrderLine.order_id == Order.id)
            .where(OrderLine.action == LineAction.RENT, Order.created_at >= recent)
            .group_by(PhysicalCopy.item_id)
            .subquery()
        )
        stmt = (
            select(CatalogItem, func.coalesce(trend_rows.c.trend, 0).label("trend"))
            .outerjoin(PhysicalCopy, PhysicalCopy.item_id == CatalogItem.id)
            .outerjoin(trend_rows, trend_rows.c.item_id == CatalogItem.id)
            .where(CatalogItem.archived.is_(False), CatalogItem.can_rent.is_(True))
            .group_by(CatalogItem.id, trend_rows.c.trend)
            .having(available > 0)
            .order_by(
                func.coalesce(trend_rows.c.trend, 0).desc(),
                CatalogItem.vote_average.desc(),
                CatalogItem.title,
            )
            .limit(max(limit * 3, 30))
        )
        seen: set[int] = set()
        if customer_id is not None:
            seen = set(
                self.session.scalars(
                    select(PhysicalCopy.item_id)
                    .join(OrderLine, OrderLine.copy_id == PhysicalCopy.id)
                    .join(Order, OrderLine.order_id == Order.id)
                    .where(Order.customer_id == customer_id)
                )
            )
        return [item for item, _trend in self.session.execute(stmt).all() if item.id not in seen][
            :30
        ]

    def cached(self, key):
        return self.session.scalar(
            select(RecommendationCache).where(RecommendationCache.cache_key == key)
        )

    def save_cache(self, key, customer_id, item_ids, expires_at):
        row = self.cached(key)
        if row is None:
            row = RecommendationCache(
                customer_id=customer_id, cache_key=key, item_ids=[], expires_at=expires_at
            )
            self.session.add(row)
        row.item_ids = item_ids
        row.expires_at = expires_at
