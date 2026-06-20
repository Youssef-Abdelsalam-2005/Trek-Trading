from __future__ import annotations

import asyncio
import logging
import os
import signal

import asyncpg

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [engine] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

TICK_INTERVAL_SECONDS = 5.0


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


async def _monitor_strategies(pool: asyncpg.Pool) -> None:
    log.debug("Strategy monitoring tick — no active strategies")


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
            await _monitor_strategies(pool)

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
