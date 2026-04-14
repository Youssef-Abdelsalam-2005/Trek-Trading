import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from backend.src.trek.engine import (
    SSE_CHANNEL,
    _estimate_current_equity,
    _halt_strategy,
    compute_drawdown,
)


class TestComputeDrawdown:
    def test_no_drawdown(self):
        assert compute_drawdown(1000.0, 1000.0) == 0.0

    def test_ten_percent_drawdown(self):
        assert abs(compute_drawdown(1000.0, 900.0) - 0.10) < 1e-9

    def test_full_drawdown(self):
        assert compute_drawdown(1000.0, 0.0) == 1.0

    def test_negative_peak_returns_zero(self):
        assert compute_drawdown(-100.0, 50.0) == 0.0

    def test_zero_peak_returns_zero(self):
        assert compute_drawdown(0.0, 50.0) == 0.0

    def test_equity_above_peak(self):
        result = compute_drawdown(1000.0, 1100.0)
        assert result < 0

    def test_small_drawdown_below_threshold(self):
        dd = compute_drawdown(1000.0, 860.0)
        assert abs(dd - 0.14) < 1e-9
        assert dd < 0.15

    def test_drawdown_at_threshold(self):
        dd = compute_drawdown(1000.0, 850.0)
        assert abs(dd - 0.15) < 1e-9

    def test_drawdown_above_threshold(self):
        dd = compute_drawdown(1000.0, 840.0)
        assert abs(dd - 0.16) < 1e-9
        assert dd > 0.15


class TestEstimateCurrentEquity:
    def _make_record(self, pnl, initial_capital=None):
        metrics = {"initial_capital_usd": initial_capital} if initial_capital is not None else {}
        return {
            "variation_id": uuid4(),
            "deployment_id": uuid4(),
            "total_pnl_usd": pnl,
            "peak_equity_usd": None,
            "metrics": metrics,
        }

    def test_positive_pnl(self):
        record = self._make_record(pnl=50.0, initial_capital=1000.0)
        assert _estimate_current_equity(record) == 1050.0

    def test_negative_pnl(self):
        record = self._make_record(pnl=-150.0, initial_capital=1000.0)
        assert _estimate_current_equity(record) == 850.0

    def test_none_pnl_returns_none(self):
        record = self._make_record(pnl=None, initial_capital=1000.0)
        assert _estimate_current_equity(record) is None

    def test_no_initial_capital_returns_none(self):
        record = self._make_record(pnl=50.0)
        assert _estimate_current_equity(record) is None


class TestHaltStrategy:
    @pytest.mark.asyncio
    async def test_halt_executes_all_statements(self):
        conn = AsyncMock()
        variation_id = uuid4()
        deployment_id = uuid4()

        await _halt_strategy(
            conn,
            variation_id=variation_id,
            deployment_id=deployment_id,
            peak_equity=1000.0,
            current_equity=800.0,
            drawdown_pct=0.20,
            threshold_pct=0.15,
        )

        assert conn.execute.call_count == 4

        calls = [str(c) for c in conn.execute.call_args_list]
        assert any("strategy_variation" in c and "halted" in c for c in calls)
        assert any("live_deployment" in c and "drawdown_halt" in c for c in calls)
        assert any("drawdown_event" in c for c in calls)
        assert any("pg_notify" in c for c in calls)

    @pytest.mark.asyncio
    async def test_halt_sends_correct_sse_payload(self):
        conn = AsyncMock()
        variation_id = uuid4()
        deployment_id = uuid4()

        await _halt_strategy(
            conn,
            variation_id=variation_id,
            deployment_id=deployment_id,
            peak_equity=1000.0,
            current_equity=800.0,
            drawdown_pct=0.20,
            threshold_pct=0.15,
        )

        notify_call = [
            c for c in conn.execute.call_args_list
            if "pg_notify" in str(c)
        ]
        assert len(notify_call) == 1
        payload_json = notify_call[0].args[1]
        payload = json.loads(payload_json)
        assert payload["type"] == "drawdown_halt"
        assert payload["variation_id"] == str(variation_id)
        assert payload["drawdown_pct"] == 0.2
        assert payload["threshold_pct"] == 0.15
