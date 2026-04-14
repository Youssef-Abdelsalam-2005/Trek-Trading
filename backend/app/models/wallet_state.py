from datetime import datetime

from sqlalchemy import DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.app.models.base import Base, TimestampMixin, UUIDPrimaryKeyMixin


class WalletState(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "wallet_state"

    wallet_address: Mapped[str] = mapped_column(String(64), nullable=False)
    sol_balance: Mapped[float] = mapped_column(Float, nullable=False)
    usdc_balance: Mapped[float] = mapped_column(Float, nullable=False)
    snapshot_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
