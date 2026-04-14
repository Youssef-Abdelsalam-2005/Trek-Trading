"""Monte Carlo shuffle and shift tests for the Skeptic pipeline (Step 24).

Runs two statistical tests to detect overfitting and look-ahead bias:
1. Label shuffle — randomizes future returns, re-runs backtest.
2. Time shift — shifts signals forward by random 1-5 bars, re-runs backtest.
"""

from __future__ import annotations

import logging
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Protocol

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

class MonteCarloConfig(BaseModel):
    """User-configurable thresholds pulled from risk_config at runtime."""

    shuffle_iterations: int = Field(default=100, ge=1)
    shift_iterations: int = Field(default=100, ge=1)
    shuffle_fail_ratio: float = Field(
        default=0.50,
        ge=0.0,
        le=1.0,
        description=(
            "Label-shuffle test FAILS if median shuffled Sortino "
            "> this fraction of the original Sortino."
        ),
    )
    shift_fail_ratio: float = Field(
        default=0.70,
        ge=0.0,
        le=1.0,
        description=(
            "Time-shift test FAILS if median shifted Sortino "
            "> this fraction of the original Sortino."
        ),
    )
    shift_min_bars: int = Field(default=1, ge=1)
    shift_max_bars: int = Field(default=5, ge=1)
    random_seed: int | None = Field(
        default=None,
        description="If set, makes all randomisation reproducible.",
    )
    max_workers: int | None = Field(
        default=None,
        description="Max parallel workers for iterations. None = sequential.",
    )


# ---------------------------------------------------------------------------
# Result models
# ---------------------------------------------------------------------------

class Verdict(str, Enum):
    PASS = "pass"
    FAIL = "fail"


class SingleTestResult(BaseModel):
    verdict: Verdict
    original_sortino: float
    threshold: float
    median_sortino: float
    mean_sortino: float
    std_sortino: float
    p_value: float = Field(
        description="Fraction of iterations where shuffled/shifted Sortino >= original."
    )
    sortino_distribution: list[float]
    iterations: int


class MonteCarloResult(BaseModel):
    overall_pass: bool
    label_shuffle: SingleTestResult
    time_shift: SingleTestResult


# ---------------------------------------------------------------------------
# Backtest callable protocol
# ---------------------------------------------------------------------------

class BacktestFn(Protocol):
    """Contract for the backtest function injected by the caller.

    Parameters
    ----------
    signals : pd.Series
        Trading signals indexed by timestamp. Values are position sizes
        (positive = long, 0 = flat; short not supported in v1).
    returns : pd.Series
        Forward returns (e.g. close-to-close pct change) aligned to the
        same index as *signals*.

    Returns
    -------
    float
        Sortino ratio of the strategy over the provided data.
    """

    def __call__(self, signals: pd.Series, returns: pd.Series) -> float: ...


# ---------------------------------------------------------------------------
# Default Sortino-based backtest (used when no external runner is injected)
# ---------------------------------------------------------------------------

def compute_sortino(signals: pd.Series, returns: pd.Series) -> float:
    """Minimal Sortino computation: annualised, using downside deviation."""
    strategy_returns = signals.shift(1) * returns
    strategy_returns = strategy_returns.dropna()
    if len(strategy_returns) < 2:
        return 0.0
    mean_ret = strategy_returns.mean()
    downside = strategy_returns[strategy_returns < 0]
    if len(downside) == 0 or downside.std() == 0:
        return float("inf") if mean_ret > 0 else 0.0
    downside_std = downside.std()
    annualisation = np.sqrt(252)
    return float((mean_ret / downside_std) * annualisation)


# ---------------------------------------------------------------------------
# Core test logic
# ---------------------------------------------------------------------------

def _run_label_shuffle(
    signals: pd.Series,
    returns: pd.Series,
    backtest_fn: BacktestFn,
    config: MonteCarloConfig,
    rng: np.random.Generator,
) -> SingleTestResult:
    """Randomise future returns, re-run backtest, compare Sortino to original."""
    original_sortino = backtest_fn(signals, returns)
    shuffled_sortinos: list[float] = []

    returns_array = returns.values.copy()

    for _ in range(config.shuffle_iterations):
        shuffled = rng.permutation(returns_array)
        shuffled_returns = pd.Series(shuffled, index=returns.index)
        s = backtest_fn(signals, shuffled_returns)
        shuffled_sortinos.append(s)

    arr = np.array(shuffled_sortinos)
    median_s = float(np.median(arr))
    threshold = config.shuffle_fail_ratio * original_sortino

    if original_sortino <= 0:
        verdict = Verdict.PASS
    elif median_s > threshold:
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.PASS

    p_value = float(np.mean(arr >= original_sortino)) if original_sortino != 0 else 1.0

    return SingleTestResult(
        verdict=verdict,
        original_sortino=original_sortino,
        threshold=threshold,
        median_sortino=median_s,
        mean_sortino=float(np.mean(arr)),
        std_sortino=float(np.std(arr)),
        p_value=p_value,
        sortino_distribution=shuffled_sortinos,
        iterations=config.shuffle_iterations,
    )


def _run_time_shift(
    signals: pd.Series,
    returns: pd.Series,
    backtest_fn: BacktestFn,
    config: MonteCarloConfig,
    rng: np.random.Generator,
) -> SingleTestResult:
    """Shift signals forward by random 1-5 bars, re-run backtest."""
    original_sortino = backtest_fn(signals, returns)
    shifted_sortinos: list[float] = []

    for _ in range(config.shift_iterations):
        shift_amount = int(rng.integers(config.shift_min_bars, config.shift_max_bars + 1))
        shifted_signals = signals.shift(shift_amount).fillna(0.0)
        s = backtest_fn(shifted_signals, returns)
        shifted_sortinos.append(s)

    arr = np.array(shifted_sortinos)
    median_s = float(np.median(arr))
    threshold = config.shift_fail_ratio * original_sortino

    if original_sortino <= 0:
        verdict = Verdict.PASS
    elif median_s > threshold:
        verdict = Verdict.FAIL
    else:
        verdict = Verdict.PASS

    p_value = float(np.mean(arr >= original_sortino)) if original_sortino != 0 else 1.0

    return SingleTestResult(
        verdict=verdict,
        original_sortino=original_sortino,
        threshold=threshold,
        median_sortino=median_s,
        mean_sortino=float(np.mean(arr)),
        std_sortino=float(np.std(arr)),
        p_value=p_value,
        sortino_distribution=shifted_sortinos,
        iterations=config.shift_iterations,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def run_monte_carlo_tests(
    signals: pd.Series,
    returns: pd.Series,
    config: MonteCarloConfig | None = None,
    backtest_fn: BacktestFn | None = None,
) -> MonteCarloResult:
    """Run both Monte Carlo tests and return a combined result.

    Parameters
    ----------
    signals
        Trading signals indexed by timestamp.
    returns
        Forward returns aligned to the same index.
    config
        Configurable thresholds and iteration counts.
    backtest_fn
        A callable ``(signals, returns) -> sortino``. Falls back to the
        built-in ``compute_sortino`` if not provided.
    """
    if config is None:
        config = MonteCarloConfig()
    if backtest_fn is None:
        backtest_fn = compute_sortino

    rng = np.random.default_rng(config.random_seed)

    label_result = _run_label_shuffle(signals, returns, backtest_fn, config, rng)
    shift_result = _run_time_shift(signals, returns, backtest_fn, config, rng)

    overall = (
        label_result.verdict == Verdict.PASS
        and shift_result.verdict == Verdict.PASS
    )

    logger.info(
        "Monte Carlo complete — shuffle=%s (median=%.4f, threshold=%.4f), "
        "shift=%s (median=%.4f, threshold=%.4f), overall=%s",
        label_result.verdict.value,
        label_result.median_sortino,
        label_result.threshold,
        shift_result.verdict.value,
        shift_result.median_sortino,
        shift_result.threshold,
        "PASS" if overall else "FAIL",
    )

    return MonteCarloResult(
        overall_pass=overall,
        label_shuffle=label_result,
        time_shift=shift_result,
    )
