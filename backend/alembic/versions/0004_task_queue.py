"""Create task_queue table

Revision ID: 0004
Revises:
Create Date: 2026-04-14
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSON, UUID

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_queue",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("task_type", sa.String(64), nullable=False),
        sa.Column("payload", JSON, nullable=True),
        sa.Column("result", JSON, nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("retry_count", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("max_retries", sa.Integer, nullable=False, server_default=sa.text("3")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_task_queue_task_type", "task_queue", ["task_type"])
    op.create_index("ix_task_queue_status", "task_queue", ["status"])
    op.create_index(
        "ix_task_queue_dequeue",
        "task_queue",
        ["task_type", "status", "scheduled_at"],
        postgresql_where=sa.text("status = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_task_queue_dequeue", table_name="task_queue")
    op.drop_index("ix_task_queue_status", table_name="task_queue")
    op.drop_index("ix_task_queue_task_type", table_name="task_queue")
    op.drop_table("task_queue")
