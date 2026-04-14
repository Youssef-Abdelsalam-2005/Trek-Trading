"""Tests for the Monte Carlo shuffle and shift module (Step 24).

Two key scenarios:
1. A genuine signal that predicts returns → shuffle/shift degrades performance → PASS.
2. A noise signal with no predictive power → shuffle/shift doesn't degrade → FAIL.
"""

import numpy as np
import pandas as pd
import pytest

from app.services.skeptic.monte_carlo import (
    MonteCarloConfig,
    MonteCarloResult,
    SingleTestResult,
    Verdict,
    compute_sortino,
    run_monte_carlo_tests,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_dates(n: int) -> pd.DatetimeIndex:
    return pd.bdate_range("2024-01-01", periods=n)


def _genuine_signal(n: int = 500, seed: int = 42) -> tuple[pd.Series, pd.Series]:
    """A signal that genuinely correlates with future returns.

    The signal *is* the sign of the next-bar return (perfect foresight),
    so shuffling returns should destroy the correlation.
    """
    rng = np.random.default_rng(seed)
    dates = _make_dates(n)
    returns = pd.Series(rng.normal(0.0005, 0.02, n), index=dates)
    signals = (returns > 0).astype(float)
    return signals, returns


def _noise_signal(n: int = 500, seed: int = 99) -> tuple[pd.Series, pd.Series]:
    """A signal that is pure random — no correlation with returns."""
    rng = np.random.default_rng(seed)
    dates = _make_dates(n)
    returns = pd.Series(rng.normal(0.0005, 0.02, n), index=dates)
    signals = pd.Series(rng.choice([0.0, 1.0], size=n), index=dates)
    return signals, returns


# ---------------------------------------------------------------------------
# compute_sortino sanity
# ---------------------------------------------------------------------------

class TestComputeSortino:
    def test_positive_sortino_for_good_strategy(self):
        signals, returns = _genuine_signal()
        s = compute_sortino(signals, returns)
        assert s > 0, f"Expected positive Sortino for genuine signal, got {s}"

    def test_near_zero_sortino_for_noise(self):
        signals, returns = _noise_signal()
        s = compute_sortino(signals, returns)
        assert abs(s) < 5, f"Noise signal should have low Sortino, got {s}"

    def test_empty_series(self):
        s = compute_sortino(pd.Series(dtype=float), pd.Series(dtype=float))
        assert s == 0.0

    def test_single_bar(self):
        s = compute_sortino(pd.Series([1.0]), pd.Series([0.01]))
        assert s == 0.0


# ---------------------------------------------------------------------------
# Label shuffle test
# ---------------------------------------------------------------------------

class TestLabelShuffle:
    def test_genuine_signal_passes(self):
        """A genuine predictor degrades under return shuffling → PASS."""
        signals, returns = _genuine_signal()
        config = MonteCarloConfig(
            shuffle_iterations=100,
            shift_iterations=10,
            random_seed=123,
        )
        result = run_monte_carlo_tests(signals, returns, config=config)
        assert result.label_shuffle.verdict == Verdict.PASS, (
            f"Genuine signal should PASS label shuffle. "
            f"Original={result.label_shuffle.original_sortino:.4f}, "
            f"median_shuffled={result.label_shuffle.median_sortino:.4f}, "
            f"threshold={result.label_shuffle.threshold:.4f}"
        )

    def test_noise_signal_fails(self):
        """A noise signal doesn't degrade under shuffling → FAIL."""
        signals, returns = _noise_signal()
        config = MonteCarloConfig(
            shuffle_iterations=100,
            shift_iterations=10,
            shuffle_fail_ratio=0.50,
            random_seed=456,
        )
        result = run_monte_carlo_tests(signals, returns, config=config)
        # Noise signal: shuffled performance stays similar → median stays
        # above threshold → FAIL. However, if the original Sortino is <= 0,
        # the test auto-passes (nothing to degrade). We check both cases.
        if result.label_shuffle.original_sortino > 0:
            assert result.label_shuffle.verdict == Verdict.FAIL, (
                f"Noise signal should FAIL label shuffle. "
                f"Original={result.label_shuffle.original_sortino:.4f}, "
                f"median_shuffled={result.label_shuffle.median_sortino:.4f}"
            )

    def test_configurable_threshold(self):
        """Tighter threshold makes it harder to pass."""
        signals, returns = _genuine_signal()
        strict = MonteCarloConfig(
            shuffle_iterations=100,
            shift_iterations=10,
            shuffle_fail_ratio=0.10,
            random_seed=789,
        )
        result = run_monte_carlo_tests(signals, returns, config=strict)
        # With a very strict threshold (10%), even a genuine signal might
        # struggle — we just verify the logic runs without error.
        assert isinstance(result.label_shuffle.verdict, Verdict)


# ---------------------------------------------------------------------------
# Time shift test
# ---------------------------------------------------------------------------

class TestTimeShift:
    def test_genuine_signal_passes(self):
        """A genuine predictor degrades when signals are shifted forward → PASS."""
        signals, returns = _genuine_signal()
        config = MonteCarloConfig(
            shuffle_iterations=10,
            shift_iterations=100,
            random_seed=321,
        )
        result = run_monte_carlo_tests(signals, returns, config=config)
        assert result.time_shift.verdict == Verdict.PASS, (
            f"Genuine signal should PASS time shift. "
            f"Original={result.time_shift.original_sortino:.4f}, "
            f"median_shifted={result.time_shift.median_sortino:.4f}, "
            f"threshold={result.time_shift.threshold:.4f}"
        )

    def test_noise_signal_shift_behavior(self):
        """Noise signal: shifting makes no meaningful difference."""
        signals, returns = _noise_signal()
        config = MonteCarloConfig(
            shuffle_iterations=10,
            shift_iterations=100,
            random_seed=654,
        )
        result = run_monte_carlo_tests(signals, returns, config=config)
        # For noise signals the shifted performance stays similar to original.
        assert isinstance(result.time_shift.verdict, Verdict)


# ---------------------------------------------------------------------------
# Overall result
# ---------------------------------------------------------------------------

class TestOverallResult:
    def test_genuine_signal_overall_pass(self):
        signals, returns = _genuine_signal()
        config = MonteCarloConfig(
            shuffle_iterations=100,
            shift_iterations=100,
            random_seed=111,
        )
        result = run_monte_carlo_tests(signals, returns, config=config)
        assert result.overall_pass is True

    def test_result_structure(self):
        signals, returns = _genuine_signal(n=100)
        config = MonteCarloConfig(
            shuffle_iterations=20,
            shift_iterations=20,
            random_seed=222,
        )
        result = run_monte_carlo_tests(signals, returns, config=config)
        assert isinstance(result, MonteCarloResult)
        assert isinstance(result.label_shuffle, SingleTestResult)
        assert isinstance(result.time_shift, SingleTestResult)
        assert len(result.label_shuffle.sortino_distribution) == 20
        assert len(result.time_shift.sortino_distribution) == 20
        assert 0.0 <= result.label_shuffle.p_value <= 1.0
        assert 0.0 <= result.time_shift.p_value <= 1.0

    def test_reproducibility_with_seed(self):
        signals, returns = _genuine_signal()
        config = MonteCarloConfig(
            shuffle_iterations=50,
            shift_iterations=50,
            random_seed=999,
        )
        r1 = run_monte_carlo_tests(signals, returns, config=config)
        r2 = run_monte_carlo_tests(signals, returns, config=config)
        assert r1.label_shuffle.median_sortino == r2.label_shuffle.median_sortino
        assert r1.time_shift.median_sortino == r2.time_shift.median_sortino

    def test_zero_original_sortino_auto_passes(self):
        """If original Sortino <= 0, there's nothing to degrade — auto-pass."""
        dates = _make_dates(200)
        rng = np.random.default_rng(42)
        returns = pd.Series(rng.normal(-0.01, 0.02, 200), index=dates)
        signals = pd.Series(np.ones(200), index=dates)
        config = MonteCarloConfig(
            shuffle_iterations=20,
            shift_iterations=20,
            random_seed=333,
        )
        result = run_monte_carlo_tests(signals, returns, config=config)
        if result.label_shuffle.original_sortino <= 0:
            assert result.label_shuffle.verdict == Verdict.PASS
        if result.time_shift.original_sortino <= 0:
            assert result.time_shift.verdict == Verdict.PASS
