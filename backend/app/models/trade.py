import uuid
from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, String
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin
from backend.app.models.enums import TradeDirection, TradeSource


class Trade(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "trade"

    variation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("strategy_variation.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source: Mapped[TradeSource] = mapped_column(nullable=False)
    direction: Mapped[TradeDirection] = mapped_column(nullable=False)
    pair: Mapped[str] = mapped_column(String(32), nullable=False, default="SOL/USDC")
    price: Mapped[float] = mapped_column(Float, nullable=False)
    quantity: Mapped[float] = mapped_column(Float, nullable=False)
    value_usd: Mapped[float] = mapped_column(Float, nullable=False)
    fee_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    slippage_bps: Mapped[float | None] = mapped_column(Float, nullable=True)
    tx_signature: Mapped[str | None] = mapped_column(String(128), nullable=True)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)
