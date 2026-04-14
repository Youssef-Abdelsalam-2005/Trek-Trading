import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import TradeDirection, TradeSource, TradeStatus


class Trade(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trade"
    __table_args__ = (
        Index("ix_trade_executed_at", "executed_at"),
        Index("ix_trade_variation_executed", "variation_id", "executed_at"),
    )

    variation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_variation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    paper_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("paper_session.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    live_deployment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("live_deployment.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source: Mapped[TradeSource] = mapped_column(nullable=False)
    direction: Mapped[TradeDirection] = mapped_column(nullable=False)
    status: Mapped[TradeStatus] = mapped_column(nullable=False, default=TradeStatus.FILLED)
    pair: Mapped[str] = mapped_column(String(32), nullable=False, default="SOL/USDC")
    input_amount: Mapped[float] = mapped_column(Float, nullable=False)
    output_amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    quoted_price: Mapped[float] = mapped_column(Float, nullable=False)
    fill_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    price_impact_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    fee_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    jito_tip_lamports: Mapped[int | None] = mapped_column(nullable=True)
    tx_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    variation: Mapped["StrategyVariation"] = relationship(
        "StrategyVariation", back_populates="trades"
    )
