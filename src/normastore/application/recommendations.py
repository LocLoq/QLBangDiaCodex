from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from normastore.domain.enums import CopyStatus, LineAction
from normastore.infrastructure.database import (
    CatalogItem,
    Order,
    OrderLine,
    PhysicalCopy,
    RecommendationCache,
)
from normastore.infrastructure.external import GeminiSearch


@dataclass(frozen=True)
class Recommendation:
    item_id: int
    title: str
    reason: str
    source: str = "Kho nội bộ"


def _candidates(session: Session, customer_id: int | None, limit: int) -> list[CatalogItem]:
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
        .order_by(func.coalesce(trend_rows.c.trend, 0).desc(), CatalogItem.vote_average.desc(), CatalogItem.title)
        .limit(max(limit * 3, 30))
    )
    seen: set[int] = set()
    if customer_id is not None:
        seen = set(
            session.scalars(
                select(PhysicalCopy.item_id)
                .join(OrderLine, OrderLine.copy_id == PhysicalCopy.id)
                .join(Order, OrderLine.order_id == Order.id)
                .where(Order.customer_id == customer_id)
            )
        )
    return [item for item, _trend in session.execute(stmt).all() if item.id not in seen][:30]


def _cache_key(customer_id: int | None) -> str:
    return f"recommendation:{'today' if customer_id is None else customer_id}:{date.today():%Y%m%d}"


def _as_utc(value: datetime) -> datetime:
    """Normalize timestamps returned by MySQL, which may lose tzinfo."""
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _from_cache(session: Session, key: str, candidates: dict[int, CatalogItem], limit: int) -> list[Recommendation] | None:
    row = session.scalar(select(RecommendationCache).where(RecommendationCache.cache_key == key))
    if not row or _as_utc(row.expires_at) <= datetime.now(timezone.utc):
        return None
    results = [
        Recommendation(item_id, candidates[item_id].title, "Đề cử đã lưu", "Cache")
        for item_id in row.item_ids
        if item_id in candidates
    ]
    return results[:limit] or None


def _save_cache(session: Session, key: str, customer_id: int | None, results: list[Recommendation], expires_at: datetime) -> None:
    row = session.scalar(select(RecommendationCache).where(RecommendationCache.cache_key == key))
    if row is None:
        row = RecommendationCache(customer_id=customer_id, cache_key=key, item_ids=[], expires_at=expires_at)
        session.add(row)
    row.item_ids = [result.item_id for result in results]
    row.expires_at = expires_at


def _recommend(
    session: Session,
    customer_id: int | None,
    limit: int,
    api_key: str | None,
    generation_model: str,
) -> list[Recommendation]:
    candidates = _candidates(session, customer_id, limit)
    by_id = {item.id: item for item in candidates}
    if not candidates:
        return []
    key = _cache_key(customer_id)
    cached = _from_cache(session, key, by_id, limit)
    if cached:
        return cached
    fallback_reason = "Đang được thuê nhiều, rating tốt và còn hàng"
    local = [Recommendation(item.id, item.title, fallback_reason) for item in candidates[:limit]]
    if not api_key:
        return local
    profile = "Khách mới; ưu tiên phim đang có hàng." if customer_id is None else "Hồ sơ ẩn danh: chỉ chọn phim mới, khác các phim đã thuê/mua trước đây."
    payload = [
        {
            "item_id": item.id,
            "title": item.title,
            "year": item.release_date.year if item.release_date else None,
            "rating": float(item.vote_average or 0),
            "overview": (item.overview or "")[:280],
        }
        for item in candidates
    ]
    ranked = GeminiSearch(api_key).rerank(generation_model, profile, payload, limit)
    if not ranked:
        return local
    results: list[Recommendation] = []
    used: set[int] = set()
    for row in ranked:
        if not isinstance(row, dict) or not isinstance(row.get("item_id"), int):
            continue
        item = by_id.get(row["item_id"])
        if not item or item.id in used:
            continue
        reason = str(row.get("reason") or fallback_reason).replace("\n", " ")[:180]
        results.append(Recommendation(item.id, item.title, reason, "AI (Gemini)"))
        used.add(item.id)
        if len(results) == limit:
            break
    for result in local:
        if len(results) == limit:
            break
        if result.item_id not in used:
            results.append(result)
    expires_at = (
        datetime.combine(date.today() + timedelta(days=1), time.min, tzinfo=timezone.utc)
        if customer_id is None
        else datetime.now(timezone.utc) + timedelta(hours=6)
    )
    _save_cache(session, key, customer_id, results, expires_at)
    return results


def today(
    session: Session,
    limit: int = 8,
    api_key: str | None = None,
    generation_model: str = "gemini-3.5-flash-lite",
) -> list[Recommendation]:
    return _recommend(session, None, limit, api_key, generation_model)


def for_customer(
    session: Session,
    customer_id: int,
    limit: int = 8,
    api_key: str | None = None,
    generation_model: str = "gemini-3.5-flash-lite",
) -> list[Recommendation]:
    return _recommend(session, customer_id, limit, api_key, generation_model)
