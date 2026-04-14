import uuid

from pydantic import Field

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class RiskConfigCreate(BaseSchema):
    per_strategy_drawdown_halt: float = Field(default=15.0, ge=0, le=100)
    portfolio_circuit_breaker: float = Field(default=25.0, ge=0, le=100)
    max_concurrent_live: int = Field(default=10, ge=1)
    paper_trading_days: int = Field(default=7, ge=1)
    max_drawdown_cap: float = Field(default=30.0, ge=0, le=100)
    pbo_fail_threshold: float = Field(default=0.40, ge=0, le=100)
    fill_failure_rate: float = Field(default=30.0, ge=0, le=100)


class RiskConfigOverrideCreate(BaseSchema):
    experiment_id: uuid.UUID
    per_strategy_drawdown_halt: float | None = Field(default=None, ge=0, le=100)
    portfolio_circuit_breaker: float | None = Field(default=None, ge=0, le=100)
    max_concurrent_live: int | None = Field(default=None, ge=1)
    paper_trading_days: int | None = Field(default=None, ge=1)
    max_drawdown_cap: float | None = Field(default=None, ge=0, le=100)
    pbo_fail_threshold: float | None = Field(default=None, ge=0, le=100)
    fill_failure_rate: float | None = Field(default=None, ge=0, le=100)


class RiskConfigUpdate(BaseSchema):
    per_strategy_drawdown_halt: float | None = Field(default=None, ge=0, le=100)
    portfolio_circuit_breaker: float | None = Field(default=None, ge=0, le=100)
    max_concurrent_live: int | None = Field(default=None, ge=1)
    paper_trading_days: int | None = Field(default=None, ge=1)
    max_drawdown_cap: float | None = Field(default=None, ge=0, le=100)
    pbo_fail_threshold: float | None = Field(default=None, ge=0, le=100)
    fill_failure_rate: float | None = Field(default=None, ge=0, le=100)


class RiskConfigResponse(BaseResponseSchema):
    experiment_id: uuid.UUID | None
    per_strategy_drawdown_halt: float | None
    portfolio_circuit_breaker: float | None
    max_concurrent_live: int | None
    paper_trading_days: int | None
    max_drawdown_cap: float | None
    pbo_fail_threshold: float | None
    fill_failure_rate: float | None


class RiskConfigResolved(BaseSchema):
    experiment_id: uuid.UUID | None
    per_strategy_drawdown_halt: float
    portfolio_circuit_breaker: float
    max_concurrent_live: int
    paper_trading_days: int
    max_drawdown_cap: float
    pbo_fail_threshold: float
    fill_failure_rate: float
