"""Add drawdown_event table and peak_equity_usd to live_deployment

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "live_deployment",
        sa.Column("peak_equity_usd", sa.Float(), nullable=True),
    )

    op.create_table(
        "drawdown_event",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "variation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("strategy_variation.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column(
            "deployment_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("live_deployment.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("peak_equity_usd", sa.Float(), nullable=False),
        sa.Column("current_equity_usd", sa.Float(), nullable=False),
        sa.Column("drawdown_pct", sa.Float(), nullable=False),
        sa.Column("threshold_pct", sa.Float(), nullable=False),
        sa.Column(
            "halted_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column("trigger", sa.String(64), nullable=False, server_default="auto"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_table("drawdown_event")
    op.drop_column("live_deployment", "peak_equity_usd")
