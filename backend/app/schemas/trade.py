import uuid
from datetime import datetime

from pydantic import Field

from backend.app.models.enums import TradeDirection, TradeSource
from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class TradeCreate(BaseSchema):
    variation_id: uuid.UUID
    source: TradeSource
    direction: TradeDirection
    pair: str = Field(default="SOL/USDC", max_length=32)
    price: float = Field(..., gt=0)
    quantity: float = Field(..., gt=0)
    value_usd: float = Field(..., gt=0)
    fee_usd: float | None = None
    slippage_bps: float | None = None
    tx_signature: str | None = None
    executed_at: datetime


class TradeResponse(BaseResponseSchema):
    variation_id: uuid.UUID
    source: TradeSource
    direction: TradeDirection
    pair: str
    price: float
    quantity: float
    value_usd: float
    fee_usd: float | None
    slippage_bps: float | None
    tx_signature: str | None
    executed_at: datetime
