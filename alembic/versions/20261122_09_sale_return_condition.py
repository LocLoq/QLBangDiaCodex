"""Keep the condition recorded when a sold disc is returned.

Revision ID: 20261122_09
Revises: 20261121_08
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122_09"
down_revision = "20261121_08"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("sale_returns")}
    if "condition_at_return" not in columns:
        op.add_column("sale_returns", sa.Column("condition_at_return", sa.String(20), nullable=True))
    # Older returns recorded the condition in the audit log, not on the return itself.
    op.execute("""
        UPDATE sale_returns AS returned
        JOIN audit_logs AS audit ON audit.id = (
            SELECT MAX(a.id) FROM audit_logs AS a
            WHERE a.action = 'RETURN_SALE' AND a.entity = 'SaleReturn'
              AND a.entity_id = CAST(returned.sale_line_id AS CHAR)
        )
        SET returned.condition_at_return = JSON_UNQUOTE(JSON_EXTRACT(audit.detail, '$.condition'))
        WHERE returned.condition_at_return IS NULL
          AND JSON_UNQUOTE(JSON_EXTRACT(audit.detail, '$.condition')) IN ('GOOD', 'WORN', 'DAMAGED')
    """)


def downgrade():
    op.drop_column("sale_returns", "condition_at_return")
