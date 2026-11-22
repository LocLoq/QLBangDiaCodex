"""Add pricing policies and per-copy condition percentage.

Revision ID: 20261121_05
Revises: 20260907_04
"""
from alembic import op
import sqlalchemy as sa

revision = "20261121_05"
down_revision = "20260907_04"
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    catalog_columns = {column["name"] for column in inspector.get_columns("catalog_items")}
    copy_columns = {column["name"] for column in inspector.get_columns("physical_copies")}
    for name in ("rental_price_mode", "sale_price_mode"):
        if name not in catalog_columns:
            op.add_column("catalog_items", sa.Column(name, sa.String(12), nullable=False, server_default="DIRECT"))
    for name in ("rental_price_percent", "sale_price_percent"):
        if name not in catalog_columns:
            op.add_column("catalog_items", sa.Column(name, sa.Numeric(7, 2), nullable=False, server_default="100"))
    if "condition_percent" not in copy_columns:
        op.add_column("physical_copies", sa.Column("condition_percent", sa.Numeric(5, 2), nullable=False, server_default="100"))
        op.execute("UPDATE physical_copies SET condition_percent = CASE `condition` WHEN 'NEW' THEN 100 WHEN 'GOOD' THEN 90 WHEN 'WORN' THEN 70 WHEN 'DAMAGED' THEN 0 ELSE 100 END")
    for name in ("rental_price_mode", "sale_price_mode"):
        if name not in copy_columns:
            op.add_column("physical_copies", sa.Column(name, sa.String(12), nullable=True))
    for name in ("rental_price_percent", "sale_price_percent"):
        if name not in copy_columns:
            op.add_column("physical_copies", sa.Column(name, sa.Numeric(7, 2), nullable=True))
    op.execute("UPDATE physical_copies SET rental_price_mode='DIRECT' WHERE rental_price_override IS NOT NULL AND rental_price_mode IS NULL")
    op.execute("UPDATE physical_copies SET sale_price_mode='DIRECT' WHERE sale_price_override IS NOT NULL AND sale_price_mode IS NULL")


def downgrade():
    for table, columns in (("physical_copies", ("sale_price_percent", "rental_price_percent", "sale_price_mode", "rental_price_mode", "condition_percent")), ("catalog_items", ("sale_price_percent", "rental_price_percent", "sale_price_mode", "rental_price_mode"))):
        for name in columns:
            op.drop_column(table, name)
