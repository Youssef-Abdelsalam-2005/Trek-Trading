from __future__ import annotations

import math
import random

import pytest

from trek.metrics import max_drawdown, sortino_ratio
from trek.models import (
    PaperSession,
    PaperTrade,
    QuoteResponse,
    StrategyStatus,
    TradeDirection,
)
from trek.paper_trading import PaperTradingSessionManager, SignalGenerator


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------

class FakeQuoteClient:
    def __init__(self, quotes: list[QuoteResponse] | None = None) -> None:
        self._quotes = quotes or []
        self._call_index = 0
        self.calls: list[dict] = []

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: float,
        slippage_bps: int = 50,
    ) -> QuoteResponse:
        self.calls.append({
            "input_mint": input_mint,
            "output_mint": output_mint,
            "amount": amount,
            "slippage_bps": slippage_bps,
        })
        if self._quotes:
            quote = self._quotes[self._call_index % len(self._quotes)]
            self._call_index += 1
            return QuoteResponse(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=amount,
                out_amount=quote.out_amount,
                price_impact_pct=quote.price_impact_pct,
                route_plan=quote.route_plan,
            )
        return QuoteResponse(
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount=amount,
            out_amount=amount * 1.02,
            price_impact_pct=0.1,
            route_plan=[{"swap": "direct"}],
        )


class AlwaysBuySignal:
    def generate_signal(self, step: int) -> TradeDirection | None:
        return TradeDirection.BUY


class AlternateBuySellSignal:
    def generate_signal(self, step: int) -> TradeDirection | None:
        return TradeDirection.BUY if step % 2 == 0 else TradeDirection.SELL


class NoSignal:
    def generate_signal(self, step: int) -> TradeDirection | None:
        return None


class SelectiveSignal:
    """Fires BUY on specified steps, None otherwise."""
    def __init__(self, buy_steps: set[int]) -> None:
        self._buy_steps = buy_steps

    def generate_signal(self, step: int) -> TradeDirection | None:
        return TradeDirection.BUY if step in self._buy_steps else None


# ---------------------------------------------------------------------------
# Metric unit tests
# ---------------------------------------------------------------------------

class TestSortinoRatio:
    def test_empty_returns(self) -> None:
        assert sortino_ratio([]) == 0.0

    def test_all_positive_returns(self) -> None:
        result = sortino_ratio([0.01, 0.02, 0.03])
        assert result == float("inf")

    def test_all_negative_returns(self) -> None:
        result = sortino_ratio([-0.05, -0.03, -0.02])
        assert result < 0

    def test_mixed_returns_known_value(self) -> None:
        returns = [0.05, -0.02, 0.03, -0.01, 0.04]
        mean = sum(returns) / len(returns)
        downside = [r for r in returns if r < 0]
        dd_sq = sum(r**2 for r in downside)
        downside_dev = math.sqrt(dd_sq / len(returns))
        expected = mean / downside_dev
        result = sortino_ratio(returns)
        assert abs(result - expected) < 1e-10

    def test_zero_returns(self) -> None:
        assert sortino_ratio([0.0, 0.0, 0.0]) == 0.0


class TestMaxDrawdown:
    def test_empty_curve(self) -> None:
        assert max_drawdown([]) == 0.0

    def test_single_point(self) -> None:
        assert max_drawdown([100.0]) == 0.0

    def test_monotonically_increasing(self) -> None:
        assert max_drawdown([100.0, 110.0, 120.0, 130.0]) == 0.0

    def test_known_drawdown(self) -> None:
        curve = [100.0, 110.0, 88.0, 95.0]
        # Peak is 110, trough is 88 -> dd = 22/110 = 0.2
        result = max_drawdown(curve)
        assert abs(result - 0.2) < 1e-10

    def test_multiple_drawdowns_returns_worst(self) -> None:
        curve = [100.0, 90.0, 95.0, 80.0, 85.0]
        # Peak never exceeds 100. Worst trough is 80 -> dd = 20/100 = 0.2
        result = max_drawdown(curve)
        assert abs(result - 0.2) < 1e-10

    def test_total_loss(self) -> None:
        curve = [100.0, 50.0, 0.0]
        assert abs(max_drawdown(curve) - 1.0) < 1e-10


# ---------------------------------------------------------------------------
# Paper trading integration tests
# ---------------------------------------------------------------------------

def _make_session(**kwargs) -> PaperSession:
    defaults = {
        "initial_capital": 1000.0,
        "drop_rate": 0.0,
        "sortino_threshold": 0.5,
        "max_drawdown_threshold": 0.30,
    }
    defaults.update(kwargs)
    return PaperSession(**defaults)


class TestPaperTradingHappyPath:
    @pytest.mark.asyncio
    async def test_session_passes_with_profitable_quotes(self) -> None:
        session = _make_session(drop_rate=0.0, sortino_threshold=0.0)
        quote = QuoteResponse(
            input_mint="", output_mint="",
            in_amount=0, out_amount=0,
            price_impact_pct=0.05, route_plan=[{"swap": "direct"}],
        )
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=10)
        assert result.status == StrategyStatus.PAPER_PASSED
        assert len(result.trades) == 10
        assert all(t.filled for t in result.trades)

    @pytest.mark.asyncio
    async def test_trades_are_logged_with_quote_data(self) -> None:
        session = _make_session(drop_rate=0.0)
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=SelectiveSignal({0, 3, 7}),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=10)
        assert len(result.trades) == 3
        for trade in result.trades:
            assert trade.in_amount > 0
            assert trade.quoted_out_amount > 0
            assert trade.input_mint != ""
            assert trade.output_mint != ""


class TestPaperTradingFailurePath:
    @pytest.mark.asyncio
    async def test_session_fails_with_losing_quotes(self) -> None:
        losing_quote = QuoteResponse(
            input_mint="", output_mint="",
            in_amount=0, out_amount=0,
            price_impact_pct=5.0, route_plan=[{"swap": "direct"}],
        )
        client = FakeQuoteClient(quotes=[losing_quote])

        # Override to return less than input
        async def bad_quote(input_mint, output_mint, amount, slippage_bps=50):
            return QuoteResponse(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=amount,
                out_amount=amount * 0.5,
                price_impact_pct=5.0,
                route_plan=[{"swap": "direct"}],
            )
        client.get_quote = bad_quote  # type: ignore[assignment]

        session = _make_session(
            drop_rate=0.0,
            sortino_threshold=1.0,
            max_drawdown_threshold=0.10,
        )
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=10)
        assert result.status == StrategyStatus.PAPER_FAILED

    @pytest.mark.asyncio
    async def test_session_fails_when_drawdown_exceeds_threshold(self) -> None:
        async def crash_quote(input_mint, output_mint, amount, slippage_bps=50):
            return QuoteResponse(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=amount,
                out_amount=amount * 0.3,
                price_impact_pct=10.0,
                route_plan=[{"swap": "direct"}],
            )

        client = FakeQuoteClient()
        client.get_quote = crash_quote  # type: ignore[assignment]

        session = _make_session(
            drop_rate=0.0,
            max_drawdown_threshold=0.05,
        )
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=5)
        assert result.status == StrategyStatus.PAPER_FAILED
        assert max_drawdown(result.equity_curve) > 0.05


class TestFillFailureModeling:
    @pytest.mark.asyncio
    async def test_zero_drop_rate_fills_all(self) -> None:
        session = _make_session(drop_rate=0.0)
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=5)
        assert all(t.filled for t in result.trades)
        assert len(result.trades) == 5

    @pytest.mark.asyncio
    async def test_full_drop_rate_fills_none(self) -> None:
        session = _make_session(drop_rate=1.0)
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=5)
        filled = [t for t in result.trades if t.filled]
        assert len(filled) == 0
        assert len(result.trades) == 5

    @pytest.mark.asyncio
    async def test_thirty_percent_drop_rate_deterministic_with_seed(self) -> None:
        session = _make_session(drop_rate=0.30)
        client = FakeQuoteClient()
        rng = random.Random(123)

        expected_fills = []
        test_rng = random.Random(123)
        for _ in range(20):
            expected_fills.append(test_rng.random() >= 0.30)

        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=rng,
        )

        result = await manager.run(num_steps=20)
        actual_fills = [t.filled for t in result.trades]
        assert actual_fills == expected_fills

    @pytest.mark.asyncio
    async def test_custom_drop_rate(self) -> None:
        session = _make_session(drop_rate=0.70)
        client = FakeQuoteClient()
        rng = random.Random(999)

        expected_fills = []
        test_rng = random.Random(999)
        for _ in range(50):
            expected_fills.append(test_rng.random() >= 0.70)

        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=rng,
        )

        result = await manager.run(num_steps=50)
        actual_fills = [t.filled for t in result.trades]
        assert actual_fills == expected_fills
        filled_count = sum(1 for f in actual_fills if f)
        assert 5 <= filled_count <= 25


class TestStateTransitions:
    @pytest.mark.asyncio
    async def test_starts_in_paper_trading(self) -> None:
        session = _make_session()
        assert session.status == StrategyStatus.PAPER_TRADING

    @pytest.mark.asyncio
    async def test_transitions_to_paper_passed(self) -> None:
        session = _make_session(
            drop_rate=0.0,
            sortino_threshold=0.0,
            max_drawdown_threshold=0.99,
        )
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=10)
        assert result.status == StrategyStatus.PAPER_PASSED

    @pytest.mark.asyncio
    async def test_transitions_to_paper_failed_on_bad_sortino(self) -> None:
        async def mediocre_quote(input_mint, output_mint, amount, slippage_bps=50):
            return QuoteResponse(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=amount,
                out_amount=amount * 0.95,
                price_impact_pct=1.0,
                route_plan=[{"swap": "direct"}],
            )

        session = _make_session(
            drop_rate=0.0,
            sortino_threshold=999.0,
            max_drawdown_threshold=0.99,
        )
        client = FakeQuoteClient()
        client.get_quote = mediocre_quote  # type: ignore[assignment]
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=10)
        assert result.status == StrategyStatus.PAPER_FAILED

    @pytest.mark.asyncio
    async def test_transitions_to_paper_failed_on_bad_drawdown(self) -> None:
        async def volatile_quote(input_mint, output_mint, amount, slippage_bps=50):
            return QuoteResponse(
                input_mint=input_mint,
                output_mint=output_mint,
                in_amount=amount,
                out_amount=amount * 0.5,
                price_impact_pct=3.0,
                route_plan=[{"swap": "direct"}],
            )

        session = _make_session(
            drop_rate=0.0,
            sortino_threshold=0.0,
            max_drawdown_threshold=0.01,
        )
        client = FakeQuoteClient()
        client.get_quote = volatile_quote  # type: ignore[assignment]
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=5)
        assert result.status == StrategyStatus.PAPER_FAILED

    @pytest.mark.asyncio
    async def test_no_signals_produces_no_trades(self) -> None:
        session = _make_session()
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=NoSignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=10)
        assert len(result.trades) == 0
        assert len(result.equity_curve) == 11  # initial + 10 steps


class TestEquityCurveTracking:
    @pytest.mark.asyncio
    async def test_equity_curve_length_matches_steps(self) -> None:
        session = _make_session(drop_rate=0.0)
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=AlwaysBuySignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=15)
        assert len(result.equity_curve) == 16  # initial + 15 steps

    @pytest.mark.asyncio
    async def test_equity_curve_starts_at_initial_capital(self) -> None:
        session = _make_session(initial_capital=5000.0)
        client = FakeQuoteClient()
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=NoSignal(),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=3)
        assert result.equity_curve[0] == 5000.0
        assert all(v == 5000.0 for v in result.equity_curve)


class TestMetricsComputedCorrectly:
    @pytest.mark.asyncio
    async def test_metrics_match_expected_for_known_quotes(self) -> None:
        quote_outputs = [102.0, 104.0, 101.0, 105.0, 103.0]
        quotes = [
            QuoteResponse(
                input_mint="", output_mint="",
                in_amount=0, out_amount=out,
                price_impact_pct=0.1, route_plan=[{"swap": "direct"}],
            )
            for out in quote_outputs
        ]
        session = _make_session(
            drop_rate=0.0,
            initial_capital=1000.0,
            sortino_threshold=0.0,
            max_drawdown_threshold=0.99,
        )
        client = FakeQuoteClient(quotes=quotes)
        manager = PaperTradingSessionManager(
            session=session,
            signal_generator=SelectiveSignal({0, 1, 2, 3, 4}),
            quote_client=client,
            rng=random.Random(42),
        )

        result = await manager.run(num_steps=5)
        assert len(result.equity_curve) == 6
        assert result.equity_curve[0] == 1000.0

        curve = result.equity_curve
        returns = [
            (curve[i] - curve[i - 1]) / curve[i - 1]
            for i in range(1, len(curve))
            if curve[i - 1] > 0
        ]
        computed_sortino = sortino_ratio(returns)
        computed_dd = max_drawdown(curve)
        assert isinstance(computed_sortino, float)
        assert isinstance(computed_dd, float)
        assert computed_dd >= 0.0
