from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np
from normastore.infrastructure.database.models import CatalogItem
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


def _embedding_matrix(
    repository, model: str, dimensions: int
) -> tuple[list[CatalogItem], np.ndarray] | None:
    key = (model, dimensions, repository.cache_marker())
    if key in _matrix_cache:
        return _matrix_cache[key]
    items = repository.catalog_items(7000)
    if not items:
        return None
    by_id = {item.id: item for item in items}
    rows = repository.embeddings(by_id, dimensions, model)
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
    repository,
    description: str,
    api_key: str | None = None,
    embedding_model: str = "gemini-embedding-001",
    embedding_dimensions: int = 768,
    limit: int = 100,
    provider_factory=GeminiSearch,
) -> SearchResponse:
    """Search rentable local catalog and return a clear provider/fallback mode."""
    terms = [term for term in description.replace(",", " ").split() if len(term) > 2]
    provider = provider_factory(api_key, embedding_model, embedding_dimensions)
    query_vector = provider.embed(description)
    if query_vector is not None and query_vector.size == embedding_dimensions:
        matrix = _embedding_matrix(repository, embedding_model, embedding_dimensions)
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
    items = repository.catalog_items(limit, terms)
    warning = provider.unavailable_reason() if api_key else "Gemini chưa được cấu hình; đang tìm trong kho nội bộ."
    return SearchResponse(
        tuple(SearchResult(item.id, item.title, item.overview or "", "Kho nội bộ") for item in items),
        "LOCAL",
        warning,
    )


def search_local(repository, description: str, api_key: str | None = None) -> list[SearchResult]:
    """Compatibility wrapper retained for existing scripts and tests."""
    provider = GeminiSearch(api_key)
    query_vector = provider.embed(description)
    if query_vector is not None:
        items = repository.catalog_items(7000)
        by_id = {item.id: item for item in items}
        rows = repository.embeddings(by_id, query_vector.size)
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
    return list(search_response(repository, description, api_key).items)
