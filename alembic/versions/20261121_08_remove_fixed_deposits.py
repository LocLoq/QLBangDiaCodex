"""Remove fixed-deposit catalog and inventory settings.

Revision ID: 20261121_08
Revises: 20261121_07
"""
from alembic import op
import sqlalchemy as sa

revision = "20261121_08"
down_revision = "20261121_07"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if 'deposit_amount' in {c['name'] for c in inspector.get_columns('catalog_items')}:
        op.drop_column('catalog_items', 'deposit_amount')
    if 'deposit_override' in {c['name'] for c in inspector.get_columns('physical_copies')}:
        op.drop_column('physical_copies', 'deposit_override')
    if inspector.has_table('deposit_defaults'):
        op.execute("DELETE FROM deposit_defaults WHERE media_format <> 'PERCENT'")


def downgrade():
    raise RuntimeError("Restore the pre-migration backup to recover fixed deposit settings.")
