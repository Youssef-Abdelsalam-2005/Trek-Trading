from __future__ import annotations

import asyncio
import logging
import os
import signal
import time

import asyncpg

from trek.services.wallet_tracker import WalletTracker

logging.basicConfig(level=logging.INFO, format="%(asctime)s [engine] %(message)s")
log = logging.getLogger(__name__)

ENGINE_TICK_SECONDS = 5


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
    pool: asyncpg.Pool | None = None
    tracker: WalletTracker | None = None

    wallet_address = os.environ.get("HOT_WALLET_ADDRESS", "")
    rpc_url = os.environ.get("SOLANA_RPC_URL", "https://api.mainnet-beta.solana.com")
    check_interval = int(os.environ.get("BALANCE_CHECK_INTERVAL_SECONDS", "300"))
    threshold = float(os.environ.get("LOW_BALANCE_THRESHOLD_USD", "100"))

    if dsn and wallet_address:
        pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
        tracker = WalletTracker(pool, rpc_url, wallet_address, threshold)
        log.info(
            "Wallet tracker enabled: address=%s interval=%ds threshold=%.2f",
            wallet_address, check_interval, threshold,
        )
    else:
        log.warning("Wallet tracking disabled — HOT_WALLET_ADDRESS or DATABASE_URL not set")

    log.info("Execution engine started — monitoring loop active")
    last_wallet_check = 0.0

    try:
        while not stop.is_set():
            now = time.monotonic()

            if tracker and (now - last_wallet_check) >= check_interval:
                try:
                    await tracker.snapshot()
                    last_wallet_check = now
                except Exception:
                    log.exception("Wallet balance check failed")
                    last_wallet_check = now

            try:
                await asyncio.wait_for(stop.wait(), timeout=ENGINE_TICK_SECONDS)
            except asyncio.TimeoutError:
                pass
    finally:
        if pool is not None:
            await pool.close()
        log.info("Execution engine shutting down")


if __name__ == "__main__":
    asyncio.run(main())
