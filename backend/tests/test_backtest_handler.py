"""Tests for the backtest handler."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trek.handlers.backtest import handle_backtest


def _utc(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


def _make_pool(variation_row, ohlcv_rows):
    """Build an asyncpg.Pool mock that returns variation + OHLCV rows."""
    conn = AsyncMock()
    conn.fetchrow = AsyncMock(return_value=variation_row)
    conn.fetch = AsyncMock(return_value=ohlcv_rows)
    conn.execute = AsyncMock()
    conn.transaction = MagicMock(return_value=AsyncMock(
        __aenter__=AsyncMock(),
        __aexit__=AsyncMock(),
    ))
    acq = AsyncMock(return_value=conn)
    acq.__aenter__ = AsyncMock(return_value=conn)
    acq.__aexit__ = AsyncMock(return_value=False)
    pool = AsyncMock()
    pool.acquire = MagicMock(return_value=acq)
    return pool, conn


def _sandbox_result():
    return {
        "sortino_ratio": 1.5,
        "sharpe_ratio": 1.2,
        "max_drawdown": -0.15,
        "total_return": 0.35,
        "win_rate": 0.6,
        "trade_count": 42,
        "equity_curve": {"timestamps": ["2024-01-01T00:00:00"], "values": [10000.0]},
        "metrics": {"init_cash": 10000.0, "final_value": 13500.0},
    }


@pytest.fixture
def variation_id():
    return uuid.uuid4()


@pytest.fixture
def payload(variation_id):
    return {
        "variation_id": str(variation_id),
        "start_date": "2024-01-01T00:00:00+00:00",
        "end_date": "2024-06-30T23:59:59+00:00",
    }


@pytest.fixture
def variation_row(variation_id):
    return {
        "id": variation_id,
        "status": "generated",
        "code": "def generate_signal(df):\n    return df['close'] * 0",
    }


@pytest.fixture
def ohlcv_rows():
    return [
        {
            "timestamp": _utc("2024-01-01T00:00:00+00:00"),
            "open": 100.0, "high": 105.0, "low": 99.0, "close": 103.0, "volume": 1000.0,
        },
        {
            "timestamp": _utc("2024-01-01T01:00:00+00:00"),
            "open": 103.0, "high": 107.0, "low": 101.0, "close": 106.0, "volume": 1200.0,
        },
    ]


@pytest.mark.asyncio
@patch("trek.handlers.backtest.run_in_sandbox")
async def test_successful_backtest(mock_sandbox, payload, variation_row, ohlcv_rows, variation_id):
    mock_sandbox.return_value = _sandbox_result()
    pool, conn = _make_pool(variation_row, ohlcv_rows)

    await handle_backtest(payload, pool)

    conn.execute.assert_any_call(
        "\nUPDATE strategy_variation SET status = $2, updated_at = now() WHERE id = $1;\n",
        variation_id,
        "backtesting",
    )
    insert_calls = [c for c in conn.execute.call_args_list if "INSERT INTO backtest_run" in str(c)]
    assert len(insert_calls) == 1
    args = insert_calls[0][0]
    assert args[11] is False  # has_error


@pytest.mark.asyncio
@patch("trek.handlers.backtest.run_in_sandbox")
async def test_sandbox_error_marks_backtested_with_error(
    mock_sandbox, payload, variation_row, ohlcv_rows, variation_id,
):
    mock_sandbox.side_effect = Exception("sandbox crash")
    pool, conn = _make_pool(variation_row, ohlcv_rows)

    await handle_backtest(payload, pool)

    insert_calls = [c for c in conn.execute.call_args_list if "INSERT INTO backtest_run" in str(c)]
    assert len(insert_calls) == 1
    args = insert_calls[0][0]
    assert args[11] is True  # has_error
    assert "sandbox crash" in args[12]  # error_message

    status_calls = [c for c in conn.execute.call_args_list if "UPDATE strategy_variation" in str(c) and "error_message" in str(c)]
    assert len(status_calls) >= 1


@pytest.mark.asyncio
async def test_wrong_status_raises(payload, variation_id):
    row = {"id": variation_id, "status": "backtested", "code": "pass"}
    pool, conn = _make_pool(row, [])

    with pytest.raises(ValueError, match="expected 'generated'"):
        await handle_backtest(payload, pool)


@pytest.mark.asyncio
async def test_missing_variation_raises(payload):
    pool, conn = _make_pool(None, [])

    with pytest.raises(ValueError, match="not found"):
        await handle_backtest(payload, pool)
