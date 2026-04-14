from __future__ import annotations

import json
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg

from trek.services.sandbox import SandboxError, run_in_sandbox
from trek.worker import register_handler

log = logging.getLogger(__name__)

FETCH_VARIATION_SQL = """
SELECT id, status, code FROM strategy_variation WHERE id = $1;
"""

UPDATE_STATUS_SQL = """
UPDATE strategy_variation SET status = $2, updated_at = now() WHERE id = $1;
"""

UPDATE_STATUS_WITH_ERROR_SQL = """
UPDATE strategy_variation SET status = $2, error_message = $3, updated_at = now() WHERE id = $1;
"""

FETCH_OHLCV_SQL = """
SELECT timestamp, open, high, low, close, volume
FROM ohlcv_data
WHERE pair = $1
  AND resolution = $2
  AND timestamp >= $3
  AND timestamp <= $4
ORDER BY timestamp ASC;
"""

INSERT_BACKTEST_RUN_SQL = """
INSERT INTO backtest_run (
    id, variation_id, start_date, end_date,
    sortino_ratio, sharpe_ratio, max_drawdown, total_return,
    win_rate, trade_count, equity_curve, has_error, error_message,
    duration_seconds, metrics, created_at, updated_at
) VALUES (
    $1, $2, $3, $4,
    $5, $6, $7, $8,
    $9, $10, $11::jsonb, $12, $13,
    $14, $15::jsonb, now(), now()
);
"""


@register_handler("backtest")
async def handle_backtest(payload: dict[str, Any], pool: asyncpg.Pool) -> None:
    variation_id = uuid.UUID(payload["variation_id"])
    start_date = datetime.fromisoformat(payload["start_date"])
    end_date = datetime.fromisoformat(payload["end_date"])
    pair = payload.get("pair", "SOL/USDC")
    resolution = payload.get("resolution", "1h")
    fee_rate = payload.get("fee_rate", 0.001)
    slippage = payload.get("slippage", 0.0005)

    log.info("Backtest starting for variation %s [%s to %s]", variation_id, start_date, end_date)

    async with pool.acquire() as conn:
        row = await conn.fetchrow(FETCH_VARIATION_SQL, variation_id)
        if row is None:
            raise ValueError(f"Strategy variation {variation_id} not found")

        current_status = row["status"]
        strategy_code = row["code"]

        if current_status != "generated":
            raise ValueError(
                f"Strategy {variation_id} is in state '{current_status}', expected 'generated'"
            )

        await conn.execute(UPDATE_STATUS_SQL, variation_id, "backtesting")

    t0 = time.monotonic()
    run_id = uuid.uuid4()
    has_error = False
    error_message = None
    metrics_result: dict[str, Any] = {}

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(FETCH_OHLCV_SQL, pair, resolution, start_date, end_date)

        if not rows:
            raise ValueError(
                f"No OHLCV data for {pair}/{resolution} between {start_date} and {end_date}"
            )

        ohlcv_records = [
            {
                "timestamp": r["timestamp"].isoformat(),
                "open": r["open"],
                "high": r["high"],
                "low": r["low"],
                "close": r["close"],
                "volume": r["volume"],
            }
            for r in rows
        ]
        ohlcv_json = json.dumps(ohlcv_records)

        log.info("Running sandbox with %d candles for variation %s", len(rows), variation_id)

        metrics_result = await run_in_sandbox(
            strategy_code,
            ohlcv_json,
            fee_rate=fee_rate,
            slippage=slippage,
        )

    except (SandboxError, ValueError) as exc:
        has_error = True
        error_message = str(exc)
        log.warning("Backtest failed for %s: %s", variation_id, error_message)
    except Exception as exc:
        has_error = True
        error_message = f"Unexpected error: {type(exc).__name__}: {exc}"
        log.exception("Backtest unexpected failure for %s", variation_id)

    duration = time.monotonic() - t0

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                INSERT_BACKTEST_RUN_SQL,
                run_id,
                variation_id,
                start_date,
                end_date,
                metrics_result.get("sortino_ratio"),
                metrics_result.get("sharpe_ratio"),
                metrics_result.get("max_drawdown"),
                metrics_result.get("total_return"),
                metrics_result.get("win_rate"),
                metrics_result.get("trade_count"),
                json.dumps(metrics_result.get("equity_curve")) if metrics_result.get("equity_curve") else None,
                has_error,
                error_message,
                duration,
                json.dumps(metrics_result.get("metrics")) if metrics_result.get("metrics") else None,
            )

            if has_error:
                await conn.execute(
                    UPDATE_STATUS_WITH_ERROR_SQL, variation_id, "backtested", error_message,
                )
            else:
                await conn.execute(UPDATE_STATUS_SQL, variation_id, "backtested")

    log.info(
        "Backtest complete for %s: has_error=%s duration=%.1fs",
        variation_id, has_error, duration,
    )
