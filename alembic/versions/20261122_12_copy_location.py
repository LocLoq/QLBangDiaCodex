"""Add physical storage locations to copies."""
from alembic import op
import sqlalchemy as sa

revision = "20261122_12"
down_revision = "20261122_11"
branch_labels = None
depends_on = None


def upgrade():
    columns = {column["name"] for column in sa.inspect(op.get_bind()).get_columns("physical_copies")}
    for name in ("aisle", "rack", "compartment"):
        if name not in columns:
            op.add_column("physical_copies", sa.Column(name, sa.String(80), nullable=True))


def downgrade():
    for name in ("compartment", "rack", "aisle"):
        op.drop_column("physical_copies", name)
