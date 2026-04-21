"""Add engine state columns to live_deployment

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
        "live_deployment",
        sa.Column("last_signal_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "live_deployment",
        sa.Column(
            "decision_interval_seconds",
            sa.Integer,
            nullable=False,
            server_default=sa.text("300"),
        ),
    )
    op.add_column(
        "live_deployment",
        sa.Column("peak_equity_usd", sa.Float, nullable=True),
    )
    op.add_column(
        "live_deployment",
        sa.Column("peak_equity_sol", sa.Float, nullable=True),
    )
    op.create_index(
        "ix_live_deployment_active",
        "live_deployment",
        ["variation_id"],
        postgresql_where=sa.text("stopped_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_live_deployment_active", table_name="live_deployment")
    op.drop_column("live_deployment", "peak_equity_sol")
    op.drop_column("live_deployment", "peak_equity_usd")
    op.drop_column("live_deployment", "decision_interval_seconds")
    op.drop_column("live_deployment", "last_signal_at")
