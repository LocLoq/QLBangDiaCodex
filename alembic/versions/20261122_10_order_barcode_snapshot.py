"""Preserve the disc barcode on each historical order line.

Revision ID: 20261122_10
Revises: 20261122_09
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122_10"
down_revision = "20261122_09"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "barcode_snapshot" not in {column["name"] for column in inspector.get_columns("order_lines")}:
        op.add_column("order_lines", sa.Column("barcode_snapshot", sa.String(80), nullable=True))
    if "ix_audit_entity_history" not in {index["name"] for index in inspector.get_indexes("audit_logs")}:
        op.create_index("ix_audit_entity_history", "audit_logs", ["action", "entity", "entity_id", "created_at"])
    op.execute("""
        UPDATE order_lines AS line
        JOIN orders AS orders ON orders.id = line.order_id
        LEFT JOIN physical_copies AS disc ON disc.id = line.copy_id
        SET line.barcode_snapshot = COALESCE(
            (SELECT JSON_UNQUOTE(JSON_EXTRACT(a.detail, '$.before.barcode'))
             FROM audit_logs AS a
             WHERE a.action = 'UPDATE_COPY' AND a.entity = 'PhysicalCopy'
               AND a.entity_id = CAST(line.copy_id AS CHAR)
               AND a.created_at > orders.created_at
               AND JSON_TYPE(JSON_EXTRACT(a.detail, '$.before.barcode')) = 'STRING'
             ORDER BY a.created_at, a.id LIMIT 1),
            disc.barcode)
        WHERE line.barcode_snapshot IS NULL
    """)


def downgrade():
    op.drop_index("ix_audit_entity_history", table_name="audit_logs")
    op.drop_column("order_lines", "barcode_snapshot")
