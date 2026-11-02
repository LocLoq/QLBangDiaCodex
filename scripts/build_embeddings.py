"""Build or refresh cached Gemini embeddings for the local catalog.

Usage: python scripts/build_embeddings.py [--limit 100]
The command sends only item title and synopsis, never customer information.
"""
from __future__ import annotations

import argparse
import sys
from functools import partial

from normastore.application.embeddings import build_embeddings
from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.infrastructure.database.unit_of_work import UnitOfWork
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
    try:
        refreshed = build_embeddings(
            partial(UnitOfWork, factory), provider, settings.gemini_embedding_model,
            settings.gemini_embedding_dimensions, args.limit,
        )
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    print(f"Đã tạo/cập nhật {refreshed} embedding.")


if __name__ == "__main__":
    main()
