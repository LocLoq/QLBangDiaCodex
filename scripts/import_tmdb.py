"""Resumable command-line importer for TMDB catalog data.

Usage: python scripts/import_tmdb.py --movies 2000 --shows 100
Set NORMASTORE_TMDB_API_KEY first. The script intentionally never embeds keys.
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from normastore.bootstrap import bootstrap
from normastore.config import Settings
from normastore.domain.enums import ItemType
from normastore.infrastructure.database import (
    CatalogItem,
    ExternalReview,
    Genre,
    ImportRun,
    ItemGenre,
    PhysicalCopy,
    Season,
    Show,
)
from normastore.infrastructure.external import TmdbClient

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def copies(session, item_id: int, count: int, prefix: str, can_sell: bool) -> None:
    for number in range(1, count + 1):
        session.add(PhysicalCopy(item_id=item_id, barcode=f"{prefix}-{number:02d}", can_sell=can_sell))


def mock_prices(seed: int) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    rental = Decimal(15000 + seed % 6 * 5000)
    sale = Decimal(100000 + seed % 9 * 50000)
    replacement = sale
    deposit = (replacement * Decimal(50 + seed % 6 * 10) / Decimal(100)).quantize(Decimal("1"))
    return rental, sale, deposit, replacement


def as_date(value: str | None) -> date | None:
    try:
        return date.fromisoformat(value or "")
    except ValueError:
        return None


def certification(detail: dict) -> str | None:
    for country in ("VN", "US"):
        for result in detail.get("release_dates", {}).get("results", []):
            if result.get("iso_3166_1") == country:
                for release in result.get("release_dates", []):
                    if release.get("certification"):
                        return release["certification"]
    return None


def sync_item_metadata(session, item: CatalogItem, detail: dict) -> None:
    for payload in detail.get("genres", []):
        name = (payload.get("name") or "").strip()
        if not name:
            continue
        genre = session.scalar(select(Genre).where(Genre.name == name))
        if not genre:
            genre = Genre(name=name)
            session.add(genre)
            session.flush()
        if not session.get(ItemGenre, {"item_id": item.id, "genre_id": genre.id}):
            session.add(ItemGenre(item_id=item.id, genre_id=genre.id))
    sync_reviews(session, detail, item_id=item.id)


def sync_reviews(session, detail: dict, item_id: int | None = None, show_id: int | None = None) -> None:
    for payload in detail.get("reviews", {}).get("results", [])[:5]:
        review_id = payload.get("id")
        content = (payload.get("content") or "").strip()
        if not review_id or not content or session.scalar(select(ExternalReview.id).where(ExternalReview.tmdb_review_id == review_id)):
            continue
        created_at = payload.get("created_at")
        try:
            published_at = datetime.fromisoformat(created_at.replace("Z", "+00:00")) if created_at else None
        except ValueError:
            published_at = None
        rating = (payload.get("author_details") or {}).get("rating")
        session.add(ExternalReview(
            item_id=item_id,
            show_id=show_id,
            tmdb_review_id=review_id,
            author=payload.get("author"),
            rating=Decimal(str(rating)) if rating is not None else None,
            content=content,
            published_at=published_at,
        ))


def resume_run(session, kind: str) -> tuple[ImportRun, int]:
    run = session.query(ImportRun).filter_by(provider="TMDB", kind=kind, status="RUNNING").order_by(ImportRun.id.desc()).first()
    if not run:
        run = ImportRun(provider="TMDB", kind=kind, checkpoint={"page": 1}, imported_count=0)
        session.add(run)
        session.flush()
    return run, int((run.checkpoint or {}).get("page", 1))


def checkpoint(session, run: ImportRun, next_page: int, imported_count: int) -> None:
    run.checkpoint = {"page": next_page}
    run.imported_count = imported_count
    session.commit()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--movies", type=int, default=2000)
    parser.add_argument("--shows", type=int, default=100)
    args = parser.parse_args()
    settings = Settings()
    if not settings.tmdb_api_key:
        raise SystemExit("Thiếu NORMASTORE_TMDB_API_KEY trong môi trường, .env hoặc .env.local.")
    factory = bootstrap(settings)
    client = TmdbClient(settings.tmdb_api_key)
    try:
        with factory() as session:
            movie_run, movie_page = resume_run(session, "MOVIE")
            movie_count = session.query(CatalogItem).filter(CatalogItem.item_type == ItemType.MOVIE, CatalogItem.tmdb_id.is_not(None)).count()
            for page in range(movie_page, 501):
                for payload in client.discover_movies(page):
                    if movie_count >= args.movies:
                        break
                    if session.query(CatalogItem).filter_by(tmdb_id=payload.tmdb_id, item_type=ItemType.MOVIE).first():
                        continue
                    detail = client.localized_movie_detail(payload.tmdb_id)
                    rental, sale, deposit, replacement = mock_prices(payload.tmdb_id)
                    can_sell = payload.tmdb_id % 10 < 7
                    item = CatalogItem(
                        item_type=ItemType.MOVIE,
                        tmdb_id=payload.tmdb_id,
                        title=detail.get("title") or payload.title,
                        overview=detail.get("overview") or payload.overview,
                        poster_path=detail.get("poster_path") or payload.poster_path,
                        vote_average=detail.get("vote_average") or payload.vote_average,
                        release_date=as_date(detail.get("release_date")),
                        runtime_minutes=detail.get("runtime"),
                        certification=certification(detail),
                        rental_price=rental,
                        sale_price=sale,
                        deposit_amount=deposit,
                        replacement_value=replacement,
                        can_sell=can_sell,
                    )
                    session.add(item)
                    session.flush()
                    sync_item_metadata(session, item, detail)
                    copies(session, item.id, 10 + (payload.tmdb_id % 11), f"TMDBM{payload.tmdb_id}", can_sell)
                    movie_count += 1
                checkpoint(session, movie_run, page + 1, movie_count)
                if movie_count >= args.movies: break
                time.sleep(0.08)
            movie_run.status = "COMPLETED"; session.commit()
            show_run, show_page = resume_run(session, "SHOW")
            show_count = session.query(Show).filter(Show.tmdb_id.is_not(None)).count()
            for page in range(show_page, 501):
                for payload in client.discover_shows(page):
                    if show_count >= args.shows: break
                    if session.query(Show).filter_by(tmdb_id=payload.tmdb_id).first(): continue
                    detail = client.localized_show_detail(payload.tmdb_id)
                    show = Show(
                        tmdb_id=payload.tmdb_id,
                        title=detail.get("name") or payload.title,
                        overview=detail.get("overview") or payload.overview,
                        poster_path=detail.get("poster_path") or payload.poster_path,
                        vote_average=detail.get("vote_average") or payload.vote_average,
                    )
                    session.add(show)
                    session.flush()
                    sync_reviews(session, detail, show_id=show.id)
                    added = 0
                    for season_info in detail.get("seasons", []):
                        number = season_info.get("season_number", 0)
                        if number == 0 or added >= 50: continue
                        season = Season(show_id=show.id, season_number=number, name=season_info.get("name") or f"Mùa {number}")
                        session.add(season); session.flush()
                        for ep in client.localized_season_detail(payload.tmdb_id, number).get("episodes", []):
                            if added >= 50: break
                            episode_seed = ep.get("id") or (payload.tmdb_id * 10000 + number * 100 + added)
                            rental, sale, deposit, replacement = mock_prices(episode_seed)
                            can_sell = episode_seed % 10 < 7
                            item = CatalogItem(item_type=ItemType.EPISODE, tmdb_id=ep.get("id"), title=f"{show.title} — T{number}E{ep.get('episode_number')}: {ep.get('name', '')}", overview=ep.get("overview") or "", poster_path=ep.get("still_path") or payload.poster_path, vote_average=ep.get("vote_average"), show_id=show.id, season_id=season.id, episode_number=ep.get("episode_number"), rental_price=Decimal("18000"), sale_price=Decimal("130000"), deposit_amount=Decimal("90000"), replacement_value=Decimal("130000"))
                            item.release_date = as_date(ep.get("air_date"))
                            item.runtime_minutes = ep.get("runtime")
                            item.rental_price = rental
                            item.sale_price = sale
                            item.deposit_amount = deposit
                            item.replacement_value = replacement
                            item.can_sell = can_sell
                            session.add(item)
                            session.flush()
                            sync_item_metadata(session, item, detail)
                            copies(session, item.id, 20 + (item.id % 11), f"TMDBE{item.id}", can_sell)
                            added += 1
                    show_count += 1
                checkpoint(session, show_run, page + 1, show_count)
                if show_count >= args.shows: break
                time.sleep(0.08)
            show_run.status = "COMPLETED"; session.commit()
        print(f"Đã import {movie_count} phim lẻ và {show_count} series.")
    except Exception as exc:
        with factory() as session:
            for kind in ("MOVIE", "SHOW"):
                run = session.query(ImportRun).filter_by(provider="TMDB", kind=kind, status="RUNNING").order_by(ImportRun.id.desc()).first()
                if run:
                    run.error = str(exc)[:4000]
            session.commit()
        raise
    finally:
        client.close()


if __name__ == "__main__":
    main()
