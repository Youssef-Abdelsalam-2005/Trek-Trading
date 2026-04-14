from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [engine] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

ADVISORY_LOCK_ID = 0x5452454B  # "TREK" in hex — prevents two engines running


# ---------------------------------------------------------------------------
# Adapter protocols — implemented by other steps, stubbed here
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Signal:
    direction: str  # "buy", "sell", "hold"
    quantity: float
    pair: str = "SOL/USDC"
    metadata: dict[str, Any] | None = None


@dataclass(frozen=True)
class TradeResult:
    direction: str
    pair: str
    price: float
    quantity: float
    value_usd: float
    fee_usd: float
    slippage_bps: float
    tx_signature: str | None
    executed_at: datetime
    metadata: dict[str, Any] | None = None


async def generate_signal(
    strategy_code: str,
    pair: str,
    resolution: str,
    pool: asyncpg.Pool,
) -> Signal:
    """Run strategy's generate_signal() on live OHLCV data via sandbox.

    Implemented in Step 25 (sandbox execution). This stub returns HOLD.
    """
    raise NotImplementedError(
        "generate_signal adapter not yet implemented — see Step 25 (sandbox execution)"
    )


async def execute_trade(signal: Signal) -> TradeResult:
    """Execute a trade via Jupiter + Jito.

    Implemented in Steps 32-33 (Jupiter swap, Jito bundles). This stub raises.
    """
    raise NotImplementedError(
        "execute_trade adapter not yet implemented — see Steps 32-33 (Jupiter/Jito)"
    )


# ---------------------------------------------------------------------------
# SQL queries
# ---------------------------------------------------------------------------

LOAD_LIVE_DEPLOYMENTS_SQL = """
SELECT
    ld.id AS deployment_id,
    ld.variation_id,
    ld.decision_interval_seconds,
    ld.last_signal_at,
    ld.total_pnl_usd,
    ld.total_pnl_sol,
    ld.peak_equity_usd,
    ld.peak_equity_sol,
    ld.trade_count,
    sv.code AS strategy_code,
    sv.status AS strategy_status
FROM live_deployment ld
JOIN strategy_variation sv ON sv.id = ld.variation_id
WHERE sv.status = 'live'
  AND ld.stopped_at IS NULL;
"""

LOAD_RISK_CONFIG_SQL = """
SELECT
    COALESCE(per_strategy_drawdown_halt, 15.0) AS per_strategy_drawdown_halt,
    COALESCE(max_concurrent_live, 10) AS max_concurrent_live
FROM risk_config
WHERE experiment_id IS NULL
LIMIT 1;
"""

INSERT_TRADE_SQL = """
INSERT INTO trade (
    id, variation_id, source, direction, pair,
    price, quantity, value_usd, fee_usd, slippage_bps,
    tx_signature, executed_at, metadata, created_at, updated_at
) VALUES (
    $1, $2, 'live', $3, $4,
    $5, $6, $7, $8, $9,
    $10, $11, $12, now(), now()
);
"""

UPDATE_DEPLOYMENT_AFTER_TRADE_SQL = """
UPDATE live_deployment
SET last_signal_at = $2,
    total_pnl_usd = COALESCE(total_pnl_usd, 0) + $3,
    total_pnl_sol = COALESCE(total_pnl_sol, 0) + $4,
    trade_count = COALESCE(trade_count, 0) + 1,
    peak_equity_usd = GREATEST(COALESCE(peak_equity_usd, 0), COALESCE(total_pnl_usd, 0) + $3),
    peak_equity_sol = GREATEST(COALESCE(peak_equity_sol, 0), COALESCE(total_pnl_sol, 0) + $4),
    updated_at = now()
WHERE id = $1;
"""

UPDATE_DEPLOYMENT_SIGNAL_ONLY_SQL = """
UPDATE live_deployment
SET last_signal_at = $2,
    updated_at = now()
WHERE id = $1;
"""

HALT_STRATEGY_SQL = """
UPDATE strategy_variation
SET status = 'halted', updated_at = now()
WHERE id = $1 AND status = 'live';
"""

STOP_DEPLOYMENT_SQL = """
UPDATE live_deployment
SET stopped_at = now(),
    stop_reason = $2,
    updated_at = now()
WHERE id = $1 AND stopped_at IS NULL;
"""

GET_DEPLOYMENT_PNL_SQL = """
SELECT total_pnl_usd, peak_equity_usd
FROM live_deployment
WHERE id = $1;
"""

KILL_ALL_LIVE_SQL = """
UPDATE strategy_variation
SET status = 'killed', updated_at = now()
WHERE status = 'live'
RETURNING id;
"""

STOP_ALL_DEPLOYMENTS_SQL = """
UPDATE live_deployment
SET stopped_at = now(),
    stop_reason = 'kill_switch',
    updated_at = now()
WHERE stopped_at IS NULL;
"""


# ---------------------------------------------------------------------------
# Per-strategy trading loop
# ---------------------------------------------------------------------------

@dataclass
class StrategyLoop:
    deployment_id: uuid.UUID
    variation_id: uuid.UUID
    strategy_code: str
    decision_interval_seconds: int
    last_signal_at: datetime | None
    task: asyncio.Task | None = None


class ExecutionEngine:
    def __init__(self, pool: asyncpg.Pool, dsn: str) -> None:
        self._pool = pool
        self._dsn = dsn
        self._stop = asyncio.Event()
        self._loops: dict[uuid.UUID, StrategyLoop] = {}  # keyed by deployment_id
        self._drawdown_threshold: float = 0.15
        self._max_concurrent_live: int = 10

    async def start(self) -> None:
        async with self._pool.acquire() as conn:
            locked = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_ID
            )
            if not locked:
                log.error(
                    "Another engine instance holds the advisory lock — exiting"
                )
                return

        log.info("Advisory lock acquired — this is the sole engine instance")

        await self._load_risk_config()
        await self._load_and_start_deployments()
        await self._listen_loop()

    async def stop(self) -> None:
        self._stop.set()
        for sl in self._loops.values():
            if sl.task and not sl.task.done():
                sl.task.cancel()
        await asyncio.gather(
            *(sl.task for sl in self._loops.values() if sl.task),
            return_exceptions=True,
        )
        log.info("All strategy loops stopped")

    async def _load_risk_config(self) -> None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(LOAD_RISK_CONFIG_SQL)
            if row:
                self._drawdown_threshold = row["per_strategy_drawdown_halt"] / 100.0
                self._max_concurrent_live = row["max_concurrent_live"]
                log.info(
                    "Risk config loaded: drawdown threshold=%.2f%%, max concurrent live=%d",
                    self._drawdown_threshold * 100,
                    self._max_concurrent_live,
                )
            else:
                log.warning(
                    "No global risk config found — using defaults: drawdown=%.2f%%, max concurrent=%d",
                    self._drawdown_threshold * 100,
                    self._max_concurrent_live,
                )

    async def _load_and_start_deployments(self) -> None:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(LOAD_LIVE_DEPLOYMENTS_SQL)

        log.info("Found %d active live deployments", len(rows))
        for row in rows:
            dep_id = row["deployment_id"]
            if dep_id in self._loops:
                continue

            if len(self._loops) >= self._max_concurrent_live:
                log.warning(
                    "Max concurrent live strategies reached (%d) — refusing deployment=%s",
                    self._max_concurrent_live,
                    dep_id,
                )
                break

            sl = StrategyLoop(
                deployment_id=dep_id,
                variation_id=row["variation_id"],
                strategy_code=row["strategy_code"],
                decision_interval_seconds=row["decision_interval_seconds"],
                last_signal_at=row["last_signal_at"],
            )
            self._start_loop(sl)

    def _start_loop(self, sl: StrategyLoop) -> None:
        sl.task = asyncio.create_task(
            self._run_strategy_loop(sl), name=f"strategy-{sl.variation_id}"
        )
        self._loops[sl.deployment_id] = sl
        log.info(
            "Started loop for deployment=%s variation=%s interval=%ds",
            sl.deployment_id,
            sl.variation_id,
            sl.decision_interval_seconds,
        )

    async def _stop_loop(self, deployment_id: uuid.UUID, reason: str) -> None:
        sl = self._loops.pop(deployment_id, None)
        if sl and sl.task and not sl.task.done():
            sl.task.cancel()
            try:
                await sl.task
            except asyncio.CancelledError:
                pass

        async with self._pool.acquire() as conn:
            await conn.execute(STOP_DEPLOYMENT_SQL, deployment_id, reason)

        log.info("Stopped deployment=%s reason=%s", deployment_id, reason)

    async def _run_strategy_loop(self, sl: StrategyLoop) -> None:
        while not self._stop.is_set():
            now = datetime.now(timezone.utc)

            if sl.last_signal_at:
                next_signal = sl.last_signal_at.timestamp() + sl.decision_interval_seconds
                wait_seconds = next_signal - now.timestamp()
                if wait_seconds > 0:
                    try:
                        await asyncio.wait_for(
                            self._stop.wait(), timeout=wait_seconds
                        )
                        if self._stop.is_set():
                            break
                    except asyncio.TimeoutError:
                        pass

            await self._execute_interval(sl)

    async def _execute_interval(self, sl: StrategyLoop) -> None:
        now = datetime.now(timezone.utc)

        try:
            sig = await generate_signal(
                strategy_code=sl.strategy_code,
                pair="SOL/USDC",
                resolution="1h",
                pool=self._pool,
            )
        except NotImplementedError:
            log.debug(
                "generate_signal not yet implemented — recording HOLD for deployment=%s",
                sl.deployment_id,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(
                    UPDATE_DEPLOYMENT_SIGNAL_ONLY_SQL, sl.deployment_id, now
                )
            sl.last_signal_at = now
            return
        except Exception:
            log.exception(
                "Signal generation failed for deployment=%s — skipping interval",
                sl.deployment_id,
            )
            sl.last_signal_at = now
            return

        if sig.direction == "hold":
            async with self._pool.acquire() as conn:
                await conn.execute(
                    UPDATE_DEPLOYMENT_SIGNAL_ONLY_SQL, sl.deployment_id, now
                )
            sl.last_signal_at = now
            log.info("HOLD signal for deployment=%s", sl.deployment_id)
            return

        try:
            result = await execute_trade(sig)
        except NotImplementedError:
            log.debug(
                "execute_trade not yet implemented — skipping trade for deployment=%s",
                sl.deployment_id,
            )
            async with self._pool.acquire() as conn:
                await conn.execute(
                    UPDATE_DEPLOYMENT_SIGNAL_ONLY_SQL, sl.deployment_id, now
                )
            sl.last_signal_at = now
            return
        except Exception:
            log.exception(
                "Trade execution failed for deployment=%s — skipping interval (fail-safe)",
                sl.deployment_id,
            )
            sl.last_signal_at = now
            return

        pnl_usd = result.value_usd if result.direction == "sell" else -result.value_usd
        pnl_sol = result.quantity if result.direction == "sell" else -result.quantity

        trade_id = uuid.uuid4()
        trade_metadata = json.dumps(result.metadata) if result.metadata else None

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                await conn.execute(
                    INSERT_TRADE_SQL,
                    trade_id,
                    sl.variation_id,
                    result.direction,
                    result.pair,
                    result.price,
                    result.quantity,
                    result.value_usd,
                    result.fee_usd,
                    result.slippage_bps,
                    result.tx_signature,
                    result.executed_at,
                    trade_metadata,
                )
                await conn.execute(
                    UPDATE_DEPLOYMENT_AFTER_TRADE_SQL,
                    sl.deployment_id,
                    now,
                    pnl_usd,
                    pnl_sol,
                )

        sl.last_signal_at = now

        log.info(
            "Trade executed: deployment=%s direction=%s price=%.4f qty=%.6f pnl_usd=%.2f tx=%s",
            sl.deployment_id,
            result.direction,
            result.price,
            result.quantity,
            pnl_usd,
            result.tx_signature or "n/a",
        )

        await self._check_drawdown(sl)

        try:
            async with self._pool.acquire() as conn:
                await conn.execute(
                    "SELECT pg_notify('live_trade_executed', $1)",
                    json.dumps({
                        "deployment_id": str(sl.deployment_id),
                        "variation_id": str(sl.variation_id),
                        "trade_id": str(trade_id),
                        "direction": result.direction,
                        "price": result.price,
                    }),
                )
        except Exception:
            log.warning("Failed to send pg_notify for trade — non-critical")

    async def _check_drawdown(self, sl: StrategyLoop) -> None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(GET_DEPLOYMENT_PNL_SQL, sl.deployment_id)

        if not row or row["peak_equity_usd"] is None or row["peak_equity_usd"] <= 0:
            return

        current_pnl = row["total_pnl_usd"] or 0.0
        peak = row["peak_equity_usd"]

        if peak <= 0:
            return

        drawdown = (peak - current_pnl) / peak

        if drawdown >= self._drawdown_threshold:
            log.warning(
                "Drawdown %.2f%% exceeds threshold %.2f%% for deployment=%s — halting",
                drawdown * 100,
                self._drawdown_threshold * 100,
                sl.deployment_id,
            )
            async with self._pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(HALT_STRATEGY_SQL, sl.variation_id)
                    await conn.execute(
                        STOP_DEPLOYMENT_SQL, sl.deployment_id, "drawdown_exceeded"
                    )
                    await conn.execute(
                        "SELECT pg_notify('risk_alert', $1)",
                        json.dumps({
                            "type": "drawdown_halt",
                            "deployment_id": str(sl.deployment_id),
                            "variation_id": str(sl.variation_id),
                            "drawdown": drawdown,
                            "threshold": self._drawdown_threshold,
                        }),
                    )

            self._loops.pop(sl.deployment_id, None)
            if sl.task and not sl.task.done():
                sl.task.cancel()

    # -----------------------------------------------------------------------
    # LISTEN/NOTIFY event loop
    # -----------------------------------------------------------------------

    async def _listen_loop(self) -> None:
        listener_conn = await asyncpg.connect(self._dsn)
        notify_event = asyncio.Event()
        pending_events: list[tuple[str, str]] = []

        def _on_notify(
            conn: asyncpg.Connection,
            pid: int,
            channel: str,
            payload: str,
        ) -> None:
            pending_events.append((channel, payload))
            notify_event.set()

        await listener_conn.add_listener("strategy_deployed", _on_notify)
        await listener_conn.add_listener("kill_switch", _on_notify)
        await listener_conn.add_listener("strategy_stopped", _on_notify)
        log.info("Listening on channels: strategy_deployed, kill_switch, strategy_stopped")

        try:
            while not self._stop.is_set():
                notify_event.clear()
                notify_task = asyncio.create_task(notify_event.wait())
                stop_task = asyncio.create_task(self._stop.wait())
                done, pending = await asyncio.wait(
                    [notify_task, stop_task],
                    return_when=asyncio.FIRST_COMPLETED,
                    timeout=60.0,
                )
                for t in pending:
                    t.cancel()

                if self._stop.is_set():
                    break

                events = pending_events[:]
                pending_events.clear()

                for channel, payload in events:
                    await self._handle_notify(channel, payload)

                if not events:
                    await self._load_and_start_deployments()

        finally:
            await listener_conn.remove_listener("strategy_deployed", _on_notify)
            await listener_conn.remove_listener("kill_switch", _on_notify)
            await listener_conn.remove_listener("strategy_stopped", _on_notify)
            await listener_conn.close()

    async def _handle_notify(self, channel: str, payload: str) -> None:
        try:
            data = json.loads(payload) if payload else {}
        except json.JSONDecodeError:
            data = {"raw": payload}

        if channel == "strategy_deployed":
            log.info("Received strategy_deployed: %s", data)
            await self._load_and_start_deployments()

        elif channel == "kill_switch":
            log.warning("Kill switch activated: %s", data)
            await self._handle_kill_switch()

        elif channel == "strategy_stopped":
            dep_id_str = data.get("deployment_id")
            if dep_id_str:
                dep_id = uuid.UUID(dep_id_str)
                reason = data.get("reason", "stopped_by_request")
                await self._stop_loop(dep_id, reason)

    async def _handle_kill_switch(self) -> None:
        for dep_id in list(self._loops.keys()):
            sl = self._loops.get(dep_id)
            if sl and sl.task and not sl.task.done():
                sl.task.cancel()
        self._loops.clear()

        async with self._pool.acquire() as conn:
            async with conn.transaction():
                killed = await conn.fetch(KILL_ALL_LIVE_SQL)
                await conn.execute(STOP_ALL_DEPLOYMENTS_SQL)

        log.warning("Kill switch: halted %d strategies", len(killed))


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    dsn = _database_url()
    if not dsn:
        log.error("DATABASE_URL not set")
        return

    pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
    log.info("Execution engine started — connected to database")

    engine = ExecutionEngine(pool, dsn)

    engine_task = asyncio.create_task(engine.start())

    await stop.wait()
    log.info("Shutdown signal received — stopping engine")

    engine._stop.set()
    await engine.stop()
    engine_task.cancel()
    try:
        await engine_task
    except asyncio.CancelledError:
        pass

    await pool.close()
    log.info("Execution engine stopped")


if __name__ == "__main__":
    asyncio.run(main())
