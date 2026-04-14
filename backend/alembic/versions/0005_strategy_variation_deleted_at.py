"""Add deleted_at to strategy_variation

Revision ID: 0005
Revises: 0004
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "strategy_variation",
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("strategy_variation", "deleted_at")
