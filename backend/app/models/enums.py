import enum


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

    @classmethod
    def terminal_states(cls) -> frozenset["StrategyStatus"]:
        return frozenset({
            cls.SKEPTIC_FAILED,
            cls.PAPER_FAILED,
            cls.KILLED,
            cls.RETIRED,
        })

    @classmethod
    def kill_switch_states(cls) -> frozenset["StrategyStatus"]:
        return frozenset({cls.LIVE, cls.PAPER_TRADING, cls.HALTED})


VALID_TRANSITIONS: dict[StrategyStatus, frozenset[StrategyStatus]] = {
    StrategyStatus.GENERATED: frozenset({StrategyStatus.BACKTESTING, StrategyStatus.RETIRED}),
    StrategyStatus.BACKTESTING: frozenset({StrategyStatus.BACKTESTED, StrategyStatus.RETIRED}),
    StrategyStatus.BACKTESTED: frozenset({StrategyStatus.SKEPTIC_PENDING, StrategyStatus.RETIRED}),
    StrategyStatus.SKEPTIC_PENDING: frozenset({
        StrategyStatus.SKEPTIC_PASSED,
        StrategyStatus.SKEPTIC_FAILED,
        StrategyStatus.RETIRED,
    }),
    StrategyStatus.SKEPTIC_PASSED: frozenset({StrategyStatus.PAPER_TRADING, StrategyStatus.RETIRED}),
    StrategyStatus.SKEPTIC_FAILED: frozenset(),
    StrategyStatus.PAPER_TRADING: frozenset({
        StrategyStatus.PAPER_PASSED,
        StrategyStatus.PAPER_FAILED,
        StrategyStatus.KILLED,
        StrategyStatus.RETIRED,
    }),
    StrategyStatus.PAPER_PASSED: frozenset({StrategyStatus.LIVE, StrategyStatus.RETIRED}),
    StrategyStatus.PAPER_FAILED: frozenset(),
    StrategyStatus.LIVE: frozenset({
        StrategyStatus.HALTED,
        StrategyStatus.KILLED,
        StrategyStatus.RETIRED,
    }),
    StrategyStatus.HALTED: frozenset({
        StrategyStatus.LIVE,
        StrategyStatus.KILLED,
        StrategyStatus.RETIRED,
    }),
    StrategyStatus.KILLED: frozenset(),
    StrategyStatus.RETIRED: frozenset(),
}


def validate_transition(current: StrategyStatus, target: StrategyStatus) -> bool:
    return target in VALID_TRANSITIONS.get(current, frozenset())


class TaskStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD_LETTER = "dead_letter"


class TradeDirection(str, enum.Enum):
    BUY = "buy"
    SELL = "sell"


class TradeSource(str, enum.Enum):
    BACKTEST = "backtest"
    PAPER = "paper"
    LIVE = "live"
