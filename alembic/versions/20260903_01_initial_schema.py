"""initial norma store schema

Revision ID: 20260903_01
Revises:
Create Date: 2026-09-03
"""
from alembic import op
from normastore.infrastructure.database.models import Base

revision = "20260903_01"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    tables = [table for table in Base.metadata.sorted_tables if table.name != "combo_items"]
    Base.metadata.create_all(bind=op.get_bind(), tables=tables)


def downgrade() -> None:
    tables = [table for table in Base.metadata.sorted_tables if table.name != "combo_items"]
    Base.metadata.drop_all(bind=op.get_bind(), tables=tables)
