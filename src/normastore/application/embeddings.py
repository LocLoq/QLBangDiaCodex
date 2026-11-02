from dataclasses import dataclass

from normastore.application.ai_search import embedding_hash, embedding_source
from normastore.infrastructure.database.repositories.embeddings import EmbeddingRepository


@dataclass(frozen=True)
class EmbeddingCandidate:
    id: int
    title: str
    overview: str | None
    cached_hash: str | None
    cached_model: str | None
    cached_dimensions: int | None


def build_embeddings(uow_factory, provider, model: str, dimensions: int, limit: int = 0) -> int:
    """Refresh embeddings, committing every 25 successful provider results."""
    with uow_factory() as uow:
        items = [
            EmbeddingCandidate(*row) for row in EmbeddingRepository(uow.session).candidates(limit)
        ]
    refreshed = 0
    batch = []
    for item in items:
        source_hash = embedding_hash(item)
        if (
            item.cached_hash == source_hash
            and item.cached_model == model
            and item.cached_dimensions == dimensions
        ):
            continue
        vector = provider.embed(embedding_source(item))
        if vector is None:
            raise RuntimeError(provider.unavailable_reason())
        values = vector.astype("float32", copy=False)
        batch.append((item.id, source_hash, values.size, values.tobytes()))
        refreshed += 1
        if len(batch) == 25:
            with uow_factory() as uow:
                EmbeddingRepository(uow.session).save_batch(batch, model)
            batch.clear()
    if batch:
        with uow_factory() as uow:
            EmbeddingRepository(uow.session).save_batch(batch, model)
    return refreshed
