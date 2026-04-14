"""Extend trade table with full logging fields

Revision ID: 0007
Revises: 0006
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    trade_status = sa.Enum("filled", "failed", "skipped", name="tradestatus")
    trade_status.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "trade",
        sa.Column(
            "paper_session_id",
            UUID(as_uuid=True),
            sa.ForeignKey("paper_session.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "trade",
        sa.Column(
            "live_deployment_id",
            UUID(as_uuid=True),
            sa.ForeignKey("live_deployment.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "trade",
        sa.Column(
            "status",
            trade_status,
            nullable=False,
            server_default="filled",
        ),
    )
    op.add_column(
        "trade",
        sa.Column("input_amount", sa.Float, nullable=False, server_default="0"),
    )
    op.add_column(
        "trade",
        sa.Column("output_amount", sa.Float, nullable=True),
    )
    op.add_column(
        "trade",
        sa.Column("quoted_price", sa.Float, nullable=False, server_default="0"),
    )
    op.add_column(
        "trade",
        sa.Column("fill_price", sa.Float, nullable=True),
    )
    op.add_column(
        "trade",
        sa.Column("price_impact_bps", sa.Float, nullable=True),
    )
    op.add_column(
        "trade",
        sa.Column("jito_tip_lamports", sa.Integer, nullable=True),
    )
    op.add_column(
        "trade",
        sa.Column("failure_reason", sa.Text, nullable=True),
    )

    # Backfill existing rows: input_amount=quantity, quoted_price=price, fill_price=price
    op.execute(
        "UPDATE trade SET input_amount = quantity, quoted_price = price, fill_price = price"
    )

    # Remove server defaults after backfill
    op.alter_column("trade", "input_amount", server_default=None)
    op.alter_column("trade", "quoted_price", server_default=None)
    op.alter_column("trade", "status", server_default=None)

    # Drop old columns that are superseded
    op.drop_column("trade", "price")
    op.drop_column("trade", "quantity")
    op.drop_column("trade", "value_usd")
    op.drop_column("trade", "metadata")

    # Add indexes
    op.create_index("ix_trade_paper_session_id", "trade", ["paper_session_id"])
    op.create_index("ix_trade_live_deployment_id", "trade", ["live_deployment_id"])
    op.create_index("ix_trade_executed_at", "trade", ["executed_at"])
    op.create_index(
        "ix_trade_variation_executed", "trade", ["variation_id", "executed_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_trade_variation_executed", table_name="trade")
    op.drop_index("ix_trade_executed_at", table_name="trade")
    op.drop_index("ix_trade_live_deployment_id", table_name="trade")
    op.drop_index("ix_trade_paper_session_id", table_name="trade")

    op.add_column("trade", sa.Column("metadata", sa.JSON, nullable=True))
    op.add_column("trade", sa.Column("value_usd", sa.Float, nullable=True))
    op.add_column("trade", sa.Column("quantity", sa.Float, nullable=True))
    op.add_column("trade", sa.Column("price", sa.Float, nullable=True))

    op.execute(
        "UPDATE trade SET price = fill_price, quantity = input_amount, "
        "value_usd = COALESCE(fill_price, quoted_price) * input_amount"
    )

    op.alter_column("trade", "price", nullable=False)
    op.alter_column("trade", "quantity", nullable=False)
    op.alter_column("trade", "value_usd", nullable=False)

    op.drop_column("trade", "failure_reason")
    op.drop_column("trade", "jito_tip_lamports")
    op.drop_column("trade", "price_impact_bps")
    op.drop_column("trade", "fill_price")
    op.drop_column("trade", "quoted_price")
    op.drop_column("trade", "output_amount")
    op.drop_column("trade", "input_amount")
    op.drop_column("trade", "status")
    op.drop_column("trade", "live_deployment_id")
    op.drop_column("trade", "paper_session_id")

    sa.Enum(name="tradestatus").drop(op.get_bind(), checkfirst=True)
