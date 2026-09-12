"""prevent duplicate TMDB catalog items during resumable imports

Revision ID: 20260904_03
Revises: 20260904_02
Create Date: 2026-09-04
"""
import sqlalchemy as sa

from alembic import op

revision = "20260904_03"
down_revision = "20260904_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    names = {constraint["name"] for constraint in inspector.get_unique_constraints("catalog_items")}
    if "uq_catalog_item_type_tmdb" not in names:
        op.create_unique_constraint("uq_catalog_item_type_tmdb", "catalog_items", ["item_type", "tmdb_id"])


def downgrade() -> None:
    op.drop_constraint("uq_catalog_item_type_tmdb", "catalog_items", type_="unique")
