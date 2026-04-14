from datetime import datetime

from backend.app.schemas.base import BaseResponseSchema


class WalletStateResponse(BaseResponseSchema):
    wallet_address: str
    sol_balance: float
    usdc_balance: float
    snapshot_at: datetime
