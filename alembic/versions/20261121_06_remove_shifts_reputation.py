"""Remove shift and customer reputation mechanisms.

Revision ID: 20261121_06
Revises: 20261121_05
"""
from alembic import op
import sqlalchemy as sa

revision = "20261121_06"
down_revision = "20261121_05"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "shift_id" in {column["name"] for column in inspector.get_columns("orders")}:
        for foreign_key in inspector.get_foreign_keys("orders"):
            if foreign_key["constrained_columns"] == ["shift_id"]:
                op.drop_constraint(foreign_key["name"], "orders", type_="foreignkey")
        op.drop_column("orders", "shift_id")
    if inspector.has_table("shifts"):
        op.drop_table("shifts")
    if inspector.has_table("reputation_events"):
        op.drop_table("reputation_events")
    if "reputation_score" in {column["name"] for column in inspector.get_columns("customers")}:
        op.drop_column("customers", "reputation_score")


def downgrade():
    raise RuntimeError("Không thể khôi phục lịch sử ca và uy tín; hãy phục hồi từ bản sao lưu.")
