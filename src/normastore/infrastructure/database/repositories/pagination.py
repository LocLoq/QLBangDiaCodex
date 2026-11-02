from sqlalchemy import func, select

from normastore.application.contracts import PagedResult, PageRequest


def page_rows(session, stmt, page_request: PageRequest) -> PagedResult:
    total_items = int(
        session.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    )
    page_size = max(1, min(page_request.page_size, 10_000))
    total_pages = max(1, (total_items + page_size - 1) // page_size)
    page = min(max(1, page_request.page), total_pages)
    rows = tuple(session.execute(stmt.offset((page - 1) * page_size).limit(page_size)).all())
    return PagedResult(rows, page, page_size, total_items, total_pages)
