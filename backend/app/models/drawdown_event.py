import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class DrawdownEvent(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "drawdown_event"

    variation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_variation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    deployment_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("live_deployment.id", ondelete="CASCADE"),
        nullable=False,
    )
    peak_equity_usd: Mapped[float] = mapped_column(Float, nullable=False)
    current_equity_usd: Mapped[float] = mapped_column(Float, nullable=False)
    drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    threshold_pct: Mapped[float] = mapped_column(Float, nullable=False)
    halted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    trigger: Mapped[str] = mapped_column(
        String(64), nullable=False, default="auto"
    )
