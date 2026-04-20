import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from backend.app.schemas.base import BaseResponseSchema, BaseSchema
from backend.app.schemas.trade import TradeResponse


class BacktestRunCreate(BaseSchema):
    variation_id: uuid.UUID
    start_date: datetime
    end_date: datetime


class BacktestRunSummary(BaseResponseSchema):
    variation_id: uuid.UUID
    start_date: datetime
    end_date: datetime
    sortino_ratio: float | None
    sharpe_ratio: float | None
    max_drawdown: float | None
    total_return: float | None
    win_rate: float | None
    trade_count: int | None
    has_error: bool
    error_message: str | None
    duration_seconds: float | None
    metrics: dict[str, Any] | None


class BacktestRunResponse(BacktestRunSummary):
    equity_curve: list[dict[str, Any]] | None


class BacktestRunDetail(BacktestRunResponse):
    trades: list[TradeResponse]
