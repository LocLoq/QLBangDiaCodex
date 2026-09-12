"""add fixed combo items

Revision ID: 20260904_02
Revises: 20260903_01
Create Date: 2026-09-04
"""
import sqlalchemy as sa

from alembic import op

revision = "20260904_02"
down_revision = "20260903_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if sa.inspect(op.get_bind()).has_table("combo_items"):
        return
    op.create_table(
        "combo_items",
        sa.Column("combo_id", sa.Integer(), sa.ForeignKey("combos.id"), primary_key=True),
        sa.Column("item_id", sa.Integer(), sa.ForeignKey("catalog_items.id"), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table("combo_items")
