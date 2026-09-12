from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from normastore.domain.enums import CopyStatus
from normastore.infrastructure.database import CatalogItem, ContentEmbedding, PhysicalCopy
from normastore.infrastructure.external import GeminiSearch


@dataclass(frozen=True)
class SearchResult:
    item_id: int
    title: str
    overview: str
    source: str
    score: float | None = None


@dataclass(frozen=True)
class SearchResponse:
    items: tuple[SearchResult, ...]
    mode: str
    warning: str | None = None


_matrix_cache: dict[tuple[str, int, str], tuple[list[CatalogItem], np.ndarray]] = {}


def clear_embedding_cache() -> None:
    _matrix_cache.clear()


def embedding_source(item: CatalogItem) -> str:
    return "\n".join((item.title, item.overview or ""))


def embedding_hash(item: CatalogItem) -> str:
    return hashlib.sha256(embedding_source(item).encode("utf-8")).hexdigest()


def _catalog_statement():
    available = func.sum((PhysicalCopy.status == CopyStatus.AVAILABLE) & PhysicalCopy.can_rent)
    return (
        select(CatalogItem)
        .outerjoin(PhysicalCopy)
        .where(CatalogItem.archived.is_(False), CatalogItem.can_rent.is_(True))
        .group_by(CatalogItem.id)
        .having(available > 0)
    )


def _cache_marker(session: Session) -> str:
    embedding_updated = session.scalar(select(func.max(ContentEmbedding.updated_at)))
    item_updated = session.scalar(select(func.max(CatalogItem.updated_at)))
    return f"{embedding_updated!s}:{item_updated!s}"


def _embedding_matrix(
    session: Session, statement, model: str, dimensions: int
) -> tuple[list[CatalogItem], np.ndarray] | None:
    key = (model, dimensions, _cache_marker(session))
    if key in _matrix_cache:
        return _matrix_cache[key]
    items = list(session.scalars(statement.limit(7000)))
    if not items:
        return None
    by_id = {item.id: item for item in items}
    rows = session.scalars(
        select(ContentEmbedding).where(
            ContentEmbedding.item_id.in_(by_id),
            ContentEmbedding.model == model,
            ContentEmbedding.dimensions == dimensions,
        )
    )
    embedded_items: list[CatalogItem] = []
    vectors: list[np.ndarray] = []
    for row in rows:
        item = by_id.get(row.item_id)
        vector = np.frombuffer(row.vector, dtype=np.float32)
        if item and vector.size == dimensions and row.source_hash == embedding_hash(item):
            embedded_items.append(item)
            vectors.append(vector)
    if not vectors:
        return None
    matrix = np.stack(vectors)
    _matrix_cache.clear()
    _matrix_cache[key] = (embedded_items, matrix)
    return embedded_items, matrix


def search_response(
    session: Session,
    description: str,
    api_key: str | None = None,
    embedding_model: str = "gemini-embedding-001",
    embedding_dimensions: int = 768,
    limit: int = 100,
) -> SearchResponse:
    """Search rentable local catalog and return a clear provider/fallback mode."""
    terms = [term for term in description.replace(",", " ").split() if len(term) > 2]
    statement = _catalog_statement()
    provider = GeminiSearch(api_key, embedding_model, embedding_dimensions)
    query_vector = provider.embed(description)
    if query_vector is not None and query_vector.size == embedding_dimensions:
        matrix = _embedding_matrix(session, statement, embedding_model, embedding_dimensions)
        if matrix:
            items, vectors = matrix
            scores = GeminiSearch.cosine(query_vector, vectors)
            ranked = sorted(
                zip(scores, items, strict=True), key=lambda result: (-float(result[0]), result[1].title)
            )[:limit]
            return SearchResponse(
                tuple(
                    SearchResult(item.id, item.title, item.overview or "", "AI (Gemini)", float(score))
                    for score, item in ranked
                ),
                "GEMINI",
            )
    if terms:
        clauses = [(CatalogItem.title.like(f"%{term}%")) | (CatalogItem.overview.like(f"%{term}%")) for term in terms]
        statement = statement.where(or_(*clauses))
    items = list(session.scalars(statement.order_by(CatalogItem.vote_average.desc(), CatalogItem.title).limit(limit)))
    warning = provider.unavailable_reason() if api_key else "Gemini chưa được cấu hình; đang tìm trong kho nội bộ."
    return SearchResponse(
        tuple(SearchResult(item.id, item.title, item.overview or "", "Kho nội bộ") for item in items),
        "LOCAL",
        warning,
    )


def search_local(session: Session, description: str, api_key: str | None = None) -> list[SearchResult]:
    """Compatibility wrapper retained for existing scripts and tests."""
    provider = GeminiSearch(api_key)
    query_vector = provider.embed(description)
    statement = _catalog_statement()
    if query_vector is not None:
        items = list(session.scalars(statement.limit(7000)))
        by_id = {item.id: item for item in items}
        rows = session.scalars(
            select(ContentEmbedding).where(
                ContentEmbedding.item_id.in_(by_id), ContentEmbedding.dimensions == query_vector.size
            )
        )
        embedded, vectors = [], []
        for row in rows:
            vector = np.frombuffer(row.vector, dtype=np.float32)
            if row.item_id in by_id and vector.size == query_vector.size:
                embedded.append(by_id[row.item_id]); vectors.append(vector)
        if vectors:
            scores = GeminiSearch.cosine(query_vector, np.stack(vectors))
            return [
                SearchResult(item.id, item.title, item.overview or "", "AI (Gemini)", float(score))
                for score, item in sorted(zip(scores, embedded, strict=True), key=lambda row: -float(row[0]))
            ]
    return list(search_response(session, description, api_key).items)
