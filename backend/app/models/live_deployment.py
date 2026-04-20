import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class LiveDeployment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "live_deployment"

    variation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_variation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    stopped_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    stop_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    total_pnl_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    total_pnl_sol: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown: Mapped[float | None] = mapped_column(Float, nullable=True)
    trade_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    metrics: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    last_signal_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_interval_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="300"
    )
    peak_equity_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    peak_equity_sol: Mapped[float | None] = mapped_column(Float, nullable=True)

    variation: Mapped["StrategyVariation"] = relationship(
        "StrategyVariation", back_populates="live_deployments"
    )
