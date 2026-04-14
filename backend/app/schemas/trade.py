import uuid
from datetime import datetime

from pydantic import Field, model_validator

from backend.app.models.enums import TradeDirection, TradeSource, TradeStatus
from backend.app.schemas.base import BaseResponseSchema, BaseSchema


class TradeCreate(BaseSchema):
    variation_id: uuid.UUID
    paper_session_id: uuid.UUID | None = None
    live_deployment_id: uuid.UUID | None = None
    source: TradeSource
    direction: TradeDirection
    status: TradeStatus = TradeStatus.FILLED
    pair: str = Field(default="SOL/USDC", max_length=32)
    input_amount: float = Field(..., gt=0)
    output_amount: float | None = Field(default=None, gt=0)
    quoted_price: float = Field(..., gt=0)
    fill_price: float | None = Field(default=None, gt=0)
    price_impact_bps: float | None = None
    fee_usd: float | None = None
    slippage_bps: float | None = None
    jito_tip_lamports: int | None = Field(default=None, ge=0)
    tx_signature: str | None = Field(default=None, max_length=128)
    failure_reason: str | None = None
    executed_at: datetime

    @model_validator(mode="after")
    def check_session_source_consistency(self):
        if self.source == TradeSource.PAPER and self.live_deployment_id is not None:
            raise ValueError("Paper trades must not have a live_deployment_id")
        if self.source == TradeSource.LIVE and self.paper_session_id is not None:
            raise ValueError("Live trades must not have a paper_session_id")
        if self.status == TradeStatus.FAILED and self.failure_reason is None:
            raise ValueError("Failed trades must include a failure_reason")
        if self.status == TradeStatus.FILLED and self.fill_price is None:
            raise ValueError("Filled trades must include a fill_price")
        return self


class TradeResponse(BaseResponseSchema):
    variation_id: uuid.UUID
    paper_session_id: uuid.UUID | None
    live_deployment_id: uuid.UUID | None
    source: TradeSource
    direction: TradeDirection
    status: TradeStatus
    pair: str
    input_amount: float
    output_amount: float | None
    quoted_price: float
    fill_price: float | None
    price_impact_bps: float | None
    fee_usd: float | None
    slippage_bps: float | None
    jito_tip_lamports: int | None
    tx_signature: str | None
    failure_reason: str | None
    executed_at: datetime


class TradeListParams(BaseSchema):
    variation_id: uuid.UUID | None = None
    experiment_id: uuid.UUID | None = None
    source: TradeSource | None = None
    status: TradeStatus | None = None
    start_date: datetime | None = None
    end_date: datetime | None = None
    limit: int = Field(default=100, ge=1, le=1000)
    offset: int = Field(default=0, ge=0)
