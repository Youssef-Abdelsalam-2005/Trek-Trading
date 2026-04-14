import asyncio
import logging
import signal

import asyncpg
import httpx

from trek.config import database_url

logging.basicConfig(level=logging.INFO, format="%(asctime)s [engine] %(message)s")
log = logging.getLogger(__name__)

OHLCV_UPDATE_INTERVAL = 3600


async def _ohlcv_update_loop(stop: asyncio.Event) -> None:
    from trek.ohlcv_fetcher import fetch_latest

    dsn = database_url()
    if not dsn:
        log.error("DATABASE_URL not set — OHLCV updates disabled")
        return

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=2)
    try:
        while not stop.is_set():
            async with httpx.AsyncClient() as client:
                try:
                    count = await fetch_latest(pool, client, "1h")
                    if count:
                        log.info("OHLCV hourly update: %d new rows", count)
                except Exception:
                    log.exception("OHLCV update failed")

            try:
                await asyncio.wait_for(stop.wait(), timeout=OHLCV_UPDATE_INTERVAL)
                break
            except TimeoutError:
                pass
    finally:
        await pool.close()


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    log.info("Execution engine started — monitoring loop active")

    ohlcv_task = asyncio.create_task(_ohlcv_update_loop(stop))

    try:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=5.0)
            except TimeoutError:
                pass
    finally:
        stop.set()
        await ohlcv_task
        log.info("Execution engine shutting down")


if __name__ == "__main__":
    asyncio.run(main())
