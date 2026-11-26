"""Persist preorder notes and the line used to fulfill a reservation."""
from alembic import op
import sqlalchemy as sa

revision = "20261126_14"
down_revision = "20261122_13"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if "note" not in {column["name"] for column in inspector.get_columns("order_lines")}:
        op.add_column("order_lines", sa.Column("note", sa.String(255), nullable=True))
    if "fulfilled_line_id" not in {column["name"] for column in inspector.get_columns("reservations")}:
        op.add_column("reservations", sa.Column("fulfilled_line_id", sa.Integer(), nullable=True))
    if not any(key["constrained_columns"] == ["fulfilled_line_id"]
               for key in sa.inspect(op.get_bind()).get_foreign_keys("reservations")):
        op.create_foreign_key("fk_reservation_fulfilled_line", "reservations", "order_lines",
                              ["fulfilled_line_id"], ["id"])


def downgrade():
    op.drop_constraint("fk_reservation_fulfilled_line", "reservations", type_="foreignkey")
    op.drop_column("reservations", "fulfilled_line_id")
    op.drop_column("order_lines", "note")
