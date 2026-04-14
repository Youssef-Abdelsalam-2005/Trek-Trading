"""Create OHLCV hypertable

Revision ID: 001
Revises:
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa

revision = "001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS timescaledb")

    op.create_table(
        "ohlcv_data",
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.Column("pair", sa.String(32), nullable=False, server_default="SOL/USD"),
        sa.Column("resolution", sa.String(16), nullable=False),
        sa.Column("open", sa.Float, nullable=False),
        sa.Column("high", sa.Float, nullable=False),
        sa.Column("low", sa.Float, nullable=False),
        sa.Column("close", sa.Float, nullable=False),
        sa.Column("volume", sa.Float, nullable=False),
        sa.PrimaryKeyConstraint("timestamp", "pair", "resolution"),
    )

    op.execute(
        "SELECT create_hypertable('ohlcv_data', 'timestamp', "
        "chunk_time_interval => INTERVAL '7 days', "
        "migrate_data => true)"
    )


def downgrade() -> None:
    op.drop_table("ohlcv_data")
