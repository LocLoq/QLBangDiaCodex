"""Record deposits applied to new rental-to-sale orders separately.

Revision ID: 20261122_11
Revises: 20261122_10
"""
from alembic import op
import sqlalchemy as sa

revision = "20261122_11"
down_revision = "20261122_10"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("orders")}
    if "deposit_applied" not in columns:
        op.add_column("orders", sa.Column("deposit_applied", sa.Numeric(14, 2), nullable=True))


def downgrade():
    raise RuntimeError("Khôi phục bản sao lưu để giữ lịch sử cấn cọc.")
