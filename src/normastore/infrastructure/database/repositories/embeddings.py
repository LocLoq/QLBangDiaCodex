from sqlalchemy import select

from normastore.infrastructure.database.models import CatalogItem, ContentEmbedding


class EmbeddingRepository:
    def __init__(self, session):
        self.session = session

    def candidates(self, limit):
        statement = (
            select(
                CatalogItem.id,
                CatalogItem.title,
                CatalogItem.overview,
                ContentEmbedding.source_hash,
                ContentEmbedding.model,
                ContentEmbedding.dimensions,
            )
            .outerjoin(ContentEmbedding, ContentEmbedding.item_id == CatalogItem.id)
            .where(CatalogItem.archived.is_(False))
            .order_by(CatalogItem.id)
        )
        if limit:
            statement = statement.limit(limit)
        return self.session.execute(statement).all()

    def save_batch(self, rows, model):
        ids = [item_id for item_id, _source_hash, _size, _vector in rows]
        existing = {
            row.item_id: row
            for row in self.session.scalars(
                select(ContentEmbedding).where(ContentEmbedding.item_id.in_(ids))
            )
        }
        for item_id, source_hash, size, vector in rows:
            cached = existing.get(item_id)
            if cached is None:
                cached = ContentEmbedding(
                    item_id=item_id,
                    model=model,
                    dimensions=size,
                    vector=vector,
                    source_hash=source_hash,
                )
                self.session.add(cached)
            else:
                cached.model = model
                cached.dimensions = size
                cached.vector = vector
                cached.source_hash = source_hash
