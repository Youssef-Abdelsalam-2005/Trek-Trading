from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
from datetime import datetime, timezone
from uuid import uuid4

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [engine] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 5.0
SSE_CHANNEL = "trek_alerts"


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def compute_drawdown(peak_equity: float, current_equity: float) -> float:
    if peak_equity <= 0:
        return 0.0
    return (peak_equity - current_equity) / peak_equity


async def _get_drawdown_threshold(conn: asyncpg.Connection) -> float:
    row = await conn.fetchrow(
        "SELECT per_strategy_stop_loss_pct FROM risk_config "
        "WHERE is_active = true ORDER BY created_at DESC LIMIT 1"
    )
    if row is None:
        return 0.15
    return float(row["per_strategy_stop_loss_pct"])


async def _get_live_strategies(conn: asyncpg.Connection) -> list[asyncpg.Record]:
    return await conn.fetch(
        """
        SELECT sv.id AS variation_id,
               ld.id AS deployment_id,
               ld.total_pnl_usd,
               ld.peak_equity_usd,
               ld.metrics
        FROM strategy_variation sv
        JOIN live_deployment ld ON ld.variation_id = sv.id
        WHERE sv.status = 'live'
          AND ld.stopped_at IS NULL
        """
    )


def _estimate_current_equity(record: asyncpg.Record) -> float | None:
    pnl = record["total_pnl_usd"]
    if pnl is None:
        return None
    metrics = record["metrics"] or {}
    initial_capital = metrics.get("initial_capital_usd")
    if initial_capital is None:
        return None
    return float(initial_capital) + float(pnl)


async def _halt_strategy(
    conn: asyncpg.Connection,
    variation_id,
    deployment_id,
    peak_equity: float,
    current_equity: float,
    drawdown_pct: float,
    threshold_pct: float,
) -> None:
    now = datetime.now(timezone.utc)
    event_id = uuid4()

    await conn.execute(
        "UPDATE strategy_variation SET status = 'halted', updated_at = $2 WHERE id = $1",
        variation_id,
        now,
    )
    await conn.execute(
        "UPDATE live_deployment SET stopped_at = $2, stop_reason = 'drawdown_halt' WHERE id = $1",
        deployment_id,
        now,
    )
    await conn.execute(
        """
        INSERT INTO drawdown_event
            (id, variation_id, deployment_id, peak_equity_usd, current_equity_usd,
             drawdown_pct, threshold_pct, halted_at, trigger, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, 'auto', $8, $8)
        """,
        event_id,
        variation_id,
        deployment_id,
        peak_equity,
        current_equity,
        drawdown_pct,
        threshold_pct,
        now,
    )

    alert_payload = json.dumps({
        "type": "drawdown_halt",
        "variation_id": str(variation_id),
        "deployment_id": str(deployment_id),
        "peak_equity_usd": peak_equity,
        "current_equity_usd": current_equity,
        "drawdown_pct": round(drawdown_pct, 4),
        "threshold_pct": threshold_pct,
        "halted_at": now.isoformat(),
    })
    await conn.execute(f"SELECT pg_notify('{SSE_CHANNEL}', $1)", alert_payload)

    log.warning(
        "Strategy %s halted: drawdown %.2f%% exceeds threshold %.2f%% "
        "(peak=%.2f, current=%.2f)",
        variation_id,
        drawdown_pct * 100,
        threshold_pct * 100,
        peak_equity,
        current_equity,
    )


async def _monitor_strategies(pool: asyncpg.Pool) -> None:
    async with pool.acquire() as conn:
        threshold = await _get_drawdown_threshold(conn)
        strategies = await _get_live_strategies(conn)

        if not strategies:
            return

        for record in strategies:
            current_equity = _estimate_current_equity(record)
            if current_equity is None:
                log.debug(
                    "Skipping strategy %s: equity data unavailable",
                    record["variation_id"],
                )
                continue

            peak = record["peak_equity_usd"]
            if peak is None or current_equity > peak:
                peak = current_equity

            await conn.execute(
                "UPDATE live_deployment SET peak_equity_usd = $2 WHERE id = $1",
                record["deployment_id"],
                peak,
            )

            drawdown_pct = compute_drawdown(peak, current_equity)

            if drawdown_pct > threshold:
                async with conn.transaction():
                    await _halt_strategy(
                        conn,
                        record["variation_id"],
                        record["deployment_id"],
                        peak,
                        current_equity,
                        drawdown_pct,
                        threshold,
                    )


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    dsn = _database_url()
    if not dsn:
        log.error("DATABASE_URL not set")
        return

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    log.info("Execution engine started — connected to database")

    try:
        while not stop.is_set():
            try:
                await _monitor_strategies(pool)
            except Exception:
                log.exception("Error in strategy monitoring tick")

            stop_task = asyncio.create_task(stop.wait())
            done, pending = await asyncio.wait(
                [stop_task],
                timeout=TICK_INTERVAL_SECONDS,
            )
            for t in pending:
                t.cancel()
    finally:
        log.info("Execution engine shutting down")
        await pool.close()
        log.info("Execution engine stopped")


if __name__ == "__main__":
    asyncio.run(main())
