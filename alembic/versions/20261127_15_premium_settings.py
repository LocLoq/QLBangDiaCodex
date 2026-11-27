"""Store configurable Premium plans and benefits."""

from alembic import op
import sqlalchemy as sa

revision = "20261127_15"
down_revision = "20261126_14"
branch_labels = None
depends_on = None


def upgrade():
    inspector = sa.inspect(op.get_bind())
    if not inspector.has_table("premium_settings"):
        op.create_table(
            "premium_settings",
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("merchandise_percent", sa.Numeric(5, 2), nullable=False),
            sa.Column("deposit_percent", sa.Numeric(5, 2), nullable=False),
        )
        op.execute(
            "INSERT INTO premium_settings (id, merchandise_percent, deposit_percent) VALUES (1, 10, 30)"
        )
    if not inspector.has_table("premium_plans"):
        op.create_table(
            "premium_plans",
            sa.Column("days", sa.Integer(), primary_key=True),
            sa.Column("price", sa.Numeric(14, 2), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
        )
        op.execute(
            "INSERT INTO premium_plans (days, price, active) VALUES (30, 59000, 1), (90, 159000, 1), (365, 499000, 1)"
        )


def downgrade():
    op.drop_table("premium_plans")
    op.drop_table("premium_settings")
