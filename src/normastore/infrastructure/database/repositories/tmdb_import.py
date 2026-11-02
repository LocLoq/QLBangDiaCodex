from sqlalchemy import select

from normastore.domain.enums import ItemType
from normastore.infrastructure.database.models import (
    CatalogItem,
    ExternalReview,
    Genre,
    ImportRun,
    ItemGenre,
    Show,
)


class TmdbImportRepository:
    def __init__(self, session):
        self.session = session

    def add_copy(self, copy):
        self.session.add(copy)

    def genre(self, name):
        return self.session.scalar(select(Genre).where(Genre.name == name))

    def add_genre(self, genre):
        self.session.add(genre)
        self.session.flush()

    def has_item_genre(self, item_id, genre_id):
        return self.session.get(ItemGenre, {"item_id": item_id, "genre_id": genre_id}) is not None

    def add_item_genre(self, item_genre):
        self.session.add(item_genre)

    def review_exists(self, review_id):
        return (
            self.session.scalar(
                select(ExternalReview.id).where(ExternalReview.tmdb_review_id == review_id)
            )
            is not None
        )

    def add_review(self, review):
        self.session.add(review)

    def running_import(self, kind):
        return (
            self.session.query(ImportRun)
            .filter_by(provider="TMDB", kind=kind, status="RUNNING")
            .order_by(ImportRun.id.desc())
            .first()
        )

    def add_import_run(self, run):
        self.session.add(run)
        self.session.flush()

    def movie_count(self):
        return (
            self.session.query(CatalogItem)
            .filter(CatalogItem.item_type == ItemType.MOVIE, CatalogItem.tmdb_id.is_not(None))
            .count()
        )

    def movie_exists(self, tmdb_id):
        return (
            self.session.query(CatalogItem)
            .filter_by(tmdb_id=tmdb_id, item_type=ItemType.MOVIE)
            .first()
            is not None
        )

    def show_count(self):
        return self.session.query(Show).filter(Show.tmdb_id.is_not(None)).count()

    def show_exists(self, tmdb_id):
        return self.session.query(Show).filter_by(tmdb_id=tmdb_id).first() is not None

    def add_item(self, item):
        self.session.add(item)
        self.session.flush()

    def add_show(self, show):
        self.session.add(show)
        self.session.flush()

    def add_season(self, season):
        self.session.add(season)
        self.session.flush()
