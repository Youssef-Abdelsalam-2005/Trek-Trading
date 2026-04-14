import uuid
from datetime import datetime

from pydantic import Field

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class PaperSessionCreate(BaseSchema):
    variation_id: uuid.UUID
    started_at: datetime
    simulated_fill_failure_rate: float = Field(default=0.3, ge=0.0, le=1.0)


class PaperSessionResponse(BaseResponseSchema):
    variation_id: uuid.UUID
    started_at: datetime
    ended_at: datetime | None
    simulated_fill_failure_rate: float
    total_return: float | None
    max_drawdown: float | None
    sortino_ratio: float | None
    trade_count: int | None
    metrics: dict | None
