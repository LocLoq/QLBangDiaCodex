"""Build or refresh cached Gemini embeddings for the local catalog.

Usage: python scripts/build_embeddings.py [--limit 100]
The command sends only item title and synopsis, never customer information.
"""
from __future__ import annotations

import argparse
import sys

from sqlalchemy import select

from normastore.application.ai_search import embedding_hash, embedding_source
from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.infrastructure.database import CatalogItem, ContentEmbedding
from normastore.infrastructure.external import GeminiSearch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Số item tối đa; 0 là toàn bộ catalog")
    args = parser.parse_args()
    settings = Settings()
    if not settings.gemini_api_key:
        raise SystemExit("Thiếu NORMASTORE_GEMINI_API_KEY trong môi trường, .env hoặc .env.local.")
    provider = GeminiSearch(
        settings.gemini_api_key,
        settings.gemini_embedding_model,
        settings.gemini_embedding_dimensions,
    )
    factory = bootstrap(settings)
    refreshed = 0
    with factory() as session:
        statement = select(CatalogItem).where(CatalogItem.archived.is_(False)).order_by(CatalogItem.id)
        if args.limit:
            statement = statement.limit(args.limit)
        for item in session.scalars(statement):
            source_hash = embedding_hash(item)
            cached = session.scalar(select(ContentEmbedding).where(ContentEmbedding.item_id == item.id))
            if (
                cached
                and cached.source_hash == source_hash
                and cached.model == settings.gemini_embedding_model
                and cached.dimensions == settings.gemini_embedding_dimensions
            ):
                continue
            vector = provider.embed(embedding_source(item))
            if vector is None:
                session.rollback()
                raise SystemExit(provider.unavailable_reason())
            values = vector.astype("float32", copy=False)
            if cached:
                cached.model = settings.gemini_embedding_model
                cached.dimensions = values.size
                cached.vector = values.tobytes()
                cached.source_hash = source_hash
            else:
                session.add(ContentEmbedding(
                    item_id=item.id,
                    model=settings.gemini_embedding_model,
                    dimensions=values.size,
                    vector=values.tobytes(),
                    source_hash=source_hash,
                ))
            refreshed += 1
            if refreshed % 25 == 0:
                session.commit()
        session.commit()
    print(f"Đã tạo/cập nhật {refreshed} embedding.")


if __name__ == "__main__":
    main()
