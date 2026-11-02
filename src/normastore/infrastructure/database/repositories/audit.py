from __future__ import annotations

from sqlalchemy import desc, select

from normastore.application.contracts import (
    AuditQuery,
    AuditView,
    PagedResult,
    PageRequest,
    SortSpec,
)
from normastore.infrastructure.database.models import (
    AuditLog,
    Employee,
)
from normastore.infrastructure.database.repositories.pagination import page_rows


class AuditQueries:
    def __init__(self, session):
        self.session = session

    def query_audit_logs(
        self,
        filters: AuditQuery = AuditQuery(),
        page_request: PageRequest = PageRequest(),
        sort: SortSpec = SortSpec("created", True),
    ) -> PagedResult[AuditView]:
        stmt = select(AuditLog, Employee).outerjoin(Employee, AuditLog.actor_id == Employee.id)
        if filters.action.strip():
            stmt = stmt.where(AuditLog.action == filters.action.strip())
        if filters.actor_id is not None:
            stmt = stmt.where(AuditLog.actor_id == filters.actor_id)
        if filters.text.strip():
            pattern = f"%{filters.text.strip()}%"
            stmt = stmt.where(
                (AuditLog.action.like(pattern))
                | (AuditLog.entity.like(pattern))
                | (AuditLog.entity_id.like(pattern))
            )
        fields = {
            "created": AuditLog.created_at,
            "actor": Employee.full_name,
            "action": AuditLog.action,
            "entity": AuditLog.entity,
            "entity_id": AuditLog.entity_id,
        }
        expression = fields.get(sort.field, AuditLog.created_at)
        page = page_rows(
            self.session,
            stmt.order_by(desc(expression) if sort.descending else expression.asc(), AuditLog.id),
            page_request,
        )
        return PagedResult(
            tuple(
                AuditView(
                    log.id,
                    log.created_at,
                    employee.full_name if employee else None,
                    log.action,
                    log.entity,
                    log.entity_id,
                    log.detail,
                )
                for log, employee in page.items
            ),
            page.page,
            page.page_size,
            page.total_items,
            page.total_pages,
        )
