"""Import the TMDB catalog with resumable checkpoints."""
from __future__ import annotations

import argparse
import sys
from functools import partial

from normastore.application.tmdb_import import run_import
from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.infrastructure.database.unit_of_work import UnitOfWork
from normastore.infrastructure.external import TmdbClient


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser()
    parser.add_argument("--movies", type=int, default=2000)
    parser.add_argument("--shows", type=int, default=100)
    args = parser.parse_args()
    settings = Settings()
    if not settings.tmdb_api_key:
        raise SystemExit("Thiếu NORMASTORE_TMDB_API_KEY trong môi trường, .env hoặc .env.local.")
    factory = bootstrap(settings)
    movie_count, show_count = run_import(partial(UnitOfWork, factory), TmdbClient(settings.tmdb_api_key), args.movies, args.shows)
    print(f"Đã import {movie_count} phim lẻ và {show_count} series.")


if __name__ == "__main__":
    main()
