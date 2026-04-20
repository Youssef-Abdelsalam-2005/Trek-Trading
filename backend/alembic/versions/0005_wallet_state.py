"""Create wallet_state table

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "wallet_state",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("wallet_address", sa.String(64), nullable=False),
        sa.Column("sol_balance", sa.Float, nullable=False),
        sa.Column("usdc_balance", sa.Float, nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_wallet_state_address_snapshot",
        "wallet_state",
        ["wallet_address", sa.text("snapshot_at DESC")],
    )


def downgrade() -> None:
    op.drop_index("ix_wallet_state_address_snapshot", table_name="wallet_state")
    op.drop_table("wallet_state")
