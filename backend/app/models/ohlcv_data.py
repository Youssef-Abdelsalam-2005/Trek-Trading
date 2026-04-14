from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base


class OHLCVData(Base):
    __tablename__ = "ohlcv_data"

    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, nullable=False
    )
    pair: Mapped[str] = mapped_column(
        String(32), primary_key=True, nullable=False, default="SOL/USD"
    )
    resolution: Mapped[str] = mapped_column(
        String(16), primary_key=True, nullable=False
    )
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False)
