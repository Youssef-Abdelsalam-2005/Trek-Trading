from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


class StrategyStatus(str, enum.Enum):
    GENERATED = "generated"
    BACKTESTING = "backtesting"
    BACKTESTED = "backtested"
    SKEPTIC_PENDING = "skeptic_pending"
    SKEPTIC_PASSED = "skeptic_passed"
    SKEPTIC_FAILED = "skeptic_failed"
    PAPER_TRADING = "paper_trading"
    PAPER_PASSED = "paper_passed"
    PAPER_FAILED = "paper_failed"
    LIVE = "live"
    HALTED = "halted"
    KILLED = "killed"
    RETIRED = "retired"


@dataclass
class QuoteResponse:
    input_mint: str
    output_mint: str
    in_amount: float
    out_amount: float
    price_impact_pct: float
    route_plan: list[dict]


class TradeDirection(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class PaperTrade:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    session_id: uuid.UUID = field(default_factory=uuid.uuid4)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    direction: TradeDirection = TradeDirection.BUY
    input_mint: str = ""
    output_mint: str = ""
    in_amount: float = 0.0
    quoted_out_amount: float = 0.0
    filled: bool = False
    price_impact_pct: float = 0.0


@dataclass
class PaperSession:
    id: uuid.UUID = field(default_factory=uuid.uuid4)
    variation_id: uuid.UUID = field(default_factory=uuid.uuid4)
    status: StrategyStatus = StrategyStatus.PAPER_TRADING
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    duration_days: int = 7
    drop_rate: float = 0.30
    sortino_threshold: float = 1.0
    max_drawdown_threshold: float = 0.30
    initial_capital: float = 1000.0
    trades: list[PaperTrade] = field(default_factory=list)
    equity_curve: list[float] = field(default_factory=list)
