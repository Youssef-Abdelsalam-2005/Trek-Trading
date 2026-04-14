import uuid
from datetime import datetime

from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class LiveDeploymentCreate(BaseSchema):
    variation_id: uuid.UUID
    started_at: datetime


class LiveDeploymentResponse(BaseResponseSchema):
    variation_id: uuid.UUID
    started_at: datetime
    stopped_at: datetime | None
    stop_reason: str | None
    total_pnl_usd: float | None
    total_pnl_sol: float | None
    max_drawdown: float | None
    trade_count: int | None
    metrics: dict | None
