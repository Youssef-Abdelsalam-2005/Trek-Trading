from pydantic import Field

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class RiskConfigCreate(BaseSchema):
    label: str = Field(default="global", max_length=64)
    max_position_size_usd: float = Field(..., gt=0)
    max_drawdown_pct: float = Field(..., gt=0, le=1.0)
    max_daily_loss_usd: float = Field(..., gt=0)
    max_concurrent_live: int = Field(default=3, ge=1)
    portfolio_stop_loss_pct: float = Field(..., gt=0, le=1.0)
    per_strategy_stop_loss_pct: float = Field(..., gt=0, le=1.0)
    paper_trading_duration_hours: int = Field(default=72, ge=1)
    min_sortino_threshold: float = Field(default=1.5)
    max_max_drawdown_pct: float = Field(default=0.15, gt=0, le=1.0)


class RiskConfigUpdate(BaseSchema):
    label: str | None = Field(default=None, max_length=64)
    is_active: bool | None = None
    max_position_size_usd: float | None = Field(default=None, gt=0)
    max_drawdown_pct: float | None = Field(default=None, gt=0, le=1.0)
    max_daily_loss_usd: float | None = Field(default=None, gt=0)
    max_concurrent_live: int | None = Field(default=None, ge=1)
    portfolio_stop_loss_pct: float | None = Field(default=None, gt=0, le=1.0)
    per_strategy_stop_loss_pct: float | None = Field(default=None, gt=0, le=1.0)
    paper_trading_duration_hours: int | None = Field(default=None, ge=1)
    min_sortino_threshold: float | None = None
    max_max_drawdown_pct: float | None = Field(default=None, gt=0, le=1.0)


class RiskConfigResponse(BaseResponseSchema):
    label: str
    is_active: bool
    max_position_size_usd: float
    max_drawdown_pct: float
    max_daily_loss_usd: float
    max_concurrent_live: int
    portfolio_stop_loss_pct: float
    per_strategy_stop_loss_pct: float
    paper_trading_duration_hours: int
    min_sortino_threshold: float
    max_max_drawdown_pct: float
