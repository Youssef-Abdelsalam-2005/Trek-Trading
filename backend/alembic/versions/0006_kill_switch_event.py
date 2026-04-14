"""Create kill_switch_event table

Revision ID: 0006
Revises: 0005
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "kill_switch_event",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("triggered_by", sa.String(64), nullable=False, server_default="user"),
        sa.Column("strategies_affected", sa.Integer, nullable=False, server_default="0"),
        sa.Column("details", JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )


def downgrade() -> None:
    op.drop_table("kill_switch_event")
