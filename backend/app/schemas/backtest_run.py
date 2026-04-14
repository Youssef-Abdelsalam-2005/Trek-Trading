import uuid
from datetime import datetime

from pydantic import Field

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class BacktestRunCreate(BaseSchema):
    variation_id: uuid.UUID
    start_date: datetime
    end_date: datetime


class BacktestRunResponse(BaseResponseSchema):
    variation_id: uuid.UUID
    start_date: datetime
    end_date: datetime
    sortino_ratio: float | None
    sharpe_ratio: float | None
    max_drawdown: float | None
    total_return: float | None
    win_rate: float | None
    trade_count: int | None
    equity_curve: dict | None
    has_error: bool
    error_message: str | None
    duration_seconds: float | None
    metrics: dict | None
