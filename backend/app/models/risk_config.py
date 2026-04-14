from sqlalchemy import Boolean, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RiskConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_config"

    label: Mapped[str] = mapped_column(
        String(64), nullable=False, default="global", unique=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    max_position_size_usd: Mapped[float] = mapped_column(Float, nullable=False)
    max_drawdown_pct: Mapped[float] = mapped_column(Float, nullable=False)
    max_daily_loss_usd: Mapped[float] = mapped_column(Float, nullable=False)
    max_concurrent_live: Mapped[int] = mapped_column(Integer, nullable=False, default=3)
    portfolio_stop_loss_pct: Mapped[float] = mapped_column(Float, nullable=False)
    per_strategy_stop_loss_pct: Mapped[float] = mapped_column(Float, nullable=False)
    paper_trading_duration_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, default=72
    )
    min_sortino_threshold: Mapped[float] = mapped_column(
        Float, nullable=False, default=1.5
    )
    max_max_drawdown_pct: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.15
    )
