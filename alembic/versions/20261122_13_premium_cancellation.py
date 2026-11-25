"""Keep the cancellation date of a Premium membership."""
from alembic import op
import sqlalchemy as sa

revision = "20261122_13"
down_revision = "20261122_12"
branch_labels = None
depends_on = None


def upgrade():
    columns = sa.inspect(op.get_bind()).get_columns("premium_memberships")
    if not any(column["name"] == "cancelled_on" for column in columns):
        op.add_column("premium_memberships", sa.Column("cancelled_on", sa.Date(), nullable=True))


def downgrade():
    columns = sa.inspect(op.get_bind()).get_columns("premium_memberships")
    if any(column["name"] == "cancelled_on" for column in columns):
        op.drop_column("premium_memberships", "cancelled_on")
