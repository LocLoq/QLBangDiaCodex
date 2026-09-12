"""add deposit defaults, mock-run markers and audit indexes

Revision ID: 20260907_04
Revises: 20260904_03
Create Date: 2026-09-07
"""

from datetime import datetime, timezone

import sqlalchemy as sa

from alembic import op

revision = "20260907_04"
down_revision = "20260904_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    now = datetime.now(timezone.utc)
    op.create_table(
        "deposit_defaults",
        sa.Column("media_format", sa.String(length=20), primary_key=True),
        sa.Column("amount", sa.Numeric(14, 2), nullable=False),
        sa.Column("updated_by", sa.Integer(), sa.ForeignKey("employees.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.bulk_insert(
        sa.table(
            "deposit_defaults",
            sa.column("media_format", sa.String),
            sa.column("amount", sa.Numeric),
            sa.column("created_at", sa.DateTime(timezone=True)),
            sa.column("updated_at", sa.DateTime(timezone=True)),
        ),
        [
            {"media_format": "VHS", "amount": 80000, "created_at": now, "updated_at": now},
            {"media_format": "VCD", "amount": 100000, "created_at": now, "updated_at": now},
            {"media_format": "DVD", "amount": 150000, "created_at": now, "updated_at": now},
            {"media_format": "Blu-ray", "amount": 250000, "created_at": now, "updated_at": now},
        ],
    )
    op.create_table(
        "mock_daily_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("business_date", sa.Date(), nullable=False, unique=True),
        sa.Column("seed_version", sa.String(length=40), nullable=False),
        sa.Column("stats", sa.JSON()),
        sa.Column("actor_id", sa.Integer(), sa.ForeignKey("employees.id")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_logs_created_at", "audit_logs", ["created_at"])
    op.create_index("ix_audit_logs_actor_created", "audit_logs", ["actor_id", "created_at"])
    op.create_index("ix_audit_logs_action_created", "audit_logs", ["action", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_action_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_created_at", table_name="audit_logs")
    op.drop_table("mock_daily_runs")
    op.drop_table("deposit_defaults")
