from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    Integer,
    String,
    Text,
    ForeignKey,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSON, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class PaperSessionRow(Base):
    __tablename__ = "paper_session"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    variation_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="paper_trading")
    start_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_days: Mapped[int] = mapped_column(Integer, nullable=False, default=7)
    drop_rate: Mapped[float] = mapped_column(Float, nullable=False, default=0.30)
    sortino_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    max_drawdown_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=0.30)
    initial_capital: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    current_capital: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)
    current_position: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    equity_curve: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    current_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_steps: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    sortino_result: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_drawdown_result: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    trades: Mapped[list[PaperTradeRow]] = relationship(
        back_populates="session", cascade="all, delete-orphan",
        order_by="PaperTradeRow.timestamp",
    )


class PaperTradeRow(Base):
    __tablename__ = "paper_trade"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("paper_session.id"), nullable=False,
    )
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        default=lambda: datetime.now(timezone.utc),
    )
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    direction: Mapped[str] = mapped_column(String(10), nullable=False)
    input_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    output_mint: Mapped[str] = mapped_column(String(64), nullable=False)
    in_amount: Mapped[float] = mapped_column(Float, nullable=False)
    quoted_out_amount: Mapped[float] = mapped_column(Float, nullable=False)
    filled: Mapped[bool] = mapped_column(Boolean, nullable=False)
    price_impact_pct: Mapped[float] = mapped_column(Float, nullable=False)
    quote_route_plan: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    session: Mapped[PaperSessionRow] = relationship(back_populates="trades")
