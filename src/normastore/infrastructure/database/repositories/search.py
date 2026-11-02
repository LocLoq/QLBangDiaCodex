from sqlalchemy import func, or_, select

from normastore.domain.enums import CopyStatus
from normastore.infrastructure.database.models import CatalogItem, ContentEmbedding, PhysicalCopy


class SearchRepository:
    def __init__(self, session):
        self.session = session

    def _catalog(self):
        available = func.sum((PhysicalCopy.status == CopyStatus.AVAILABLE) & PhysicalCopy.can_rent)
        return (
            select(CatalogItem)
            .outerjoin(PhysicalCopy)
            .where(CatalogItem.archived.is_(False), CatalogItem.can_rent.is_(True))
            .group_by(CatalogItem.id)
            .having(available > 0)
        )

    def cache_marker(self):
        embedding_updated = self.session.scalar(select(func.max(ContentEmbedding.updated_at)))
        item_updated = self.session.scalar(select(func.max(CatalogItem.updated_at)))
        return f"{embedding_updated!s}:{item_updated!s}"

    def catalog_items(self, limit, terms=None):
        statement = self._catalog()
        if terms is not None:
            if terms:
                clauses = [
                    CatalogItem.title.like(f"%{term}%") | CatalogItem.overview.like(f"%{term}%")
                    for term in terms
                ]
                statement = statement.where(or_(*clauses))
            statement = statement.order_by(CatalogItem.vote_average.desc(), CatalogItem.title)
        return list(self.session.scalars(statement.limit(limit)))

    def embeddings(self, item_ids, dimensions, model=None):
        statement = select(ContentEmbedding).where(
            ContentEmbedding.item_id.in_(item_ids), ContentEmbedding.dimensions == dimensions
        )
        if model is not None:
            statement = statement.where(ContentEmbedding.model == model)
        return self.session.scalars(statement)
