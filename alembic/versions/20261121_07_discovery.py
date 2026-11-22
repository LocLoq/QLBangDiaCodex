"""Add per-title discovery discounts.

Revision ID: 20261121_07
Revises: 20261121_06
"""
from alembic import op
import sqlalchemy as sa

revision = "20261121_07"
down_revision = "20261121_06"
branch_labels = None
depends_on = None


def upgrade():
    existing = {column['name'] for column in sa.inspect(op.get_bind()).get_columns('catalog_items')}
    columns = (
        sa.Column('discovery_discount_percent', sa.Numeric(5, 2), nullable=False, server_default='0'),
        sa.Column('discovery_discount_active', sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column('discovery_discount_starts', sa.Date(), nullable=True),
        sa.Column('discovery_discount_ends', sa.Date(), nullable=True),
    )
    for column in columns:
        if column.name not in existing:
            op.add_column('catalog_items', column)


def downgrade():
    for name in ('discovery_discount_ends', 'discovery_discount_starts', 'discovery_discount_active', 'discovery_discount_percent'):
        op.drop_column('catalog_items', name)
