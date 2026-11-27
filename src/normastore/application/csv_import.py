from datetime import date
from decimal import Decimal

from normastore.application.contracts import BusinessError
from normastore.domain.enums import ItemType
from normastore.infrastructure.database.models import Season


def _boolean(value, default=True):
    value = value.strip().lower()
    if not value:
        return default
    if value in ("1", "true", "yes"):
        return True
    if value in ("0", "false", "no"):
        return False
    raise ValueError("Giá trị có/không phải là 1, 0, true hoặc false.")


def _number(value, default):
    result = Decimal(value.strip() or default)
    if not result.is_finite() or result < 0:
        raise ValueError("Giá phải là số không âm.")
    return result


def import_catalog(operations, rows, actor_id):
    operations._require_manager(actor_id)
    shows = {}
    for number, row in enumerate(rows, 2):
        if row.get("type", "").strip().upper() != "SHOW":
            continue
        try:
            title = row.get("title", "").strip()
            reference = row.get("show_ref", "").strip()
            if not title or not reference or reference in shows:
                raise ValueError("Bộ phim cần tên và show_ref duy nhất.")
            if operations.catalog_queries.show_by_title(title):
                raise ValueError("Tên bộ phim đã tồn tại.")
            shows[reference] = operations.create_show(title, row.get("overview", ""), actor_id)
        except Exception as exc:
            raise BusinessError(f"Dòng {number}: {exc}") from exc
    count = len(shows)
    for number, row in enumerate(rows, 2):
        kind = row.get("type", "").strip().upper()
        if kind == "SHOW":
            continue
        try:
            if kind not in ("MOVIE", "EPISODE"):
                raise ValueError("type phải là MOVIE, SHOW hoặc EPISODE.")
            title = row.get("title", "").strip()
            if not title or len(title) > 255:
                raise ValueError("Tên phim là bắt buộc và tối đa 255 ký tự.")
            released = (
                date.fromisoformat(row["release_date"].strip())
                if row.get("release_date", "").strip()
                else None
            )
            data = dict(
                item_type=ItemType(kind),
                title=title,
                overview=row.get("overview", "").strip() or None,
                release_date=released,
                rental_price=_number(row.get("rental_price", ""), "25000"),
                sale_price=_number(row.get("sale_price", ""), "200000"),
                replacement_value=_number(row.get("replacement_value", ""), "250000"),
                can_rent=_boolean(row.get("can_rent", "")),
                can_sell=_boolean(row.get("can_sell", "")),
                genre_names=[x.strip() for x in row.get("genres", "").split("|") if x.strip()],
            )
            if not data["can_rent"] and not data["can_sell"]:
                raise ValueError("Phim phải cho thuê hoặc bán.")
            if kind == "MOVIE":
                if operations.catalog_queries.movie_by_title_date(title, released):
                    raise ValueError("Phim lẻ cùng tên và ngày phát hành đã tồn tại.")
            else:
                reference = row.get("show_ref", "").strip()
                show_id = row.get("show_id", "").strip()
                if bool(reference) == bool(show_id):
                    raise ValueError("Chọn một trong show_ref hoặc show_id.")
                show = (
                    shows.get(reference)
                    if reference
                    else operations.catalog_queries.get_show(int(show_id))
                )
                if not show or show.archived:
                    raise ValueError("Không tìm thấy bộ phim.")
                season_number = int(row.get("season", ""))
                episode_number = int(row.get("episode", ""))
                if season_number < 1 or episode_number < 1:
                    raise ValueError("Số mùa và tập phải là số nguyên dương.")
                season = operations.catalog_queries.fetch_add_episodes_bulk_season(
                    season_number, show.id
                )
                if not season:
                    season = Season(
                        show_id=show.id, season_number=season_number, name=f"Mùa {season_number}"
                    )
                    operations.catalog_queries.add_season(season)
                    operations.catalog_queries.flush()
                if (
                    episode_number
                    in operations.catalog_queries.fetch_add_episodes_bulk_existing_numbers(
                        season, show.id
                    )
                ):
                    raise ValueError("Tập phim đã tồn tại trong mùa.")
                data.update(show_id=show.id, season_id=season.id, episode_number=episode_number)
            operations.save_catalog_item(actor_id, **data)
            count += 1
        except Exception as exc:
            raise BusinessError(f"Dòng {number}: {exc}") from exc
    return count


def import_copies(operations, rows, actor_id):
    operations._require_manager(actor_id)
    count = 0
    for number, row in enumerate(rows, 2):
        try:
            media = row.get("media_format", "").strip() or "DVD"
            if media not in ("VHS", "VCD", "DVD", "Blu-ray"):
                raise ValueError("Định dạng đĩa không hợp lệ.")
            copies = operations.add_copies(
                int(row.get("item_id", "")),
                int(row.get("quantity", "1") or "1"),
                media,
                actor_id,
                _boolean(row.get("can_rent", "")),
                _boolean(row.get("can_sell", "")),
                row.get("aisle", ""),
                row.get("rack", ""),
                row.get("compartment", ""),
            )
            count += len(copies)
        except Exception as exc:
            raise BusinessError(f"Dòng {number}: {exc}") from exc
    return count
