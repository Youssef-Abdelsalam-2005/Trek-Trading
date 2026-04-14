import uuid

from sqlalchemy import Float, ForeignKey, Integer, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class RiskConfig(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "risk_config"
    __table_args__ = (
        UniqueConstraint("experiment_id", name="uq_risk_config_experiment_id"),
    )

    experiment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("experiment.id", ondelete="CASCADE"),
        nullable=True,
        default=None,
    )

    per_strategy_drawdown_halt: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    portfolio_circuit_breaker: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    max_concurrent_live: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    paper_trading_days: Mapped[int | None] = mapped_column(
        Integer, nullable=True, default=None
    )
    max_drawdown_cap: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    pbo_fail_threshold: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )
    fill_failure_rate: Mapped[float | None] = mapped_column(
        Float, nullable=True, default=None
    )

    GLOBAL_DEFAULTS: dict = {
        "per_strategy_drawdown_halt": 15.0,
        "portfolio_circuit_breaker": 25.0,
        "max_concurrent_live": 10,
        "paper_trading_days": 7,
        "max_drawdown_cap": 30.0,
        "pbo_fail_threshold": 0.40,
        "fill_failure_rate": 30.0,
    }

    RISK_FIELDS: list[str] = list(GLOBAL_DEFAULTS.keys())
