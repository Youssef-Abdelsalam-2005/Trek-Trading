from datetime import datetime

from pydantic import Field

from backend.app.schemas.base import BaseSchema


class OHLCVDataPoint(BaseSchema):
    timestamp: datetime
    pair: str = Field(default="SOL/USDC", max_length=32)
    resolution: str = Field(..., max_length=16)
    open: float
    high: float
    low: float
    close: float
    volume: float = Field(..., ge=0)
