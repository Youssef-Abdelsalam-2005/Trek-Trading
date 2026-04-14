"""OHLCV data fetcher — pulls SOL/USDC candles from Birdeye and stores them in TimescaleDB.

Birdeye's /defi/ohlcv endpoint returns actual Solana DEX OHLCV candles for
a given token, aggregated across on-chain liquidity pools. This gives us
real SOL/USDC trading data from Solana DEXes (Raydium, Orca, etc.), which
matches the pairs the system executes against.

Requires BIRDEYE_API_KEY environment variable.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import time
from datetime import datetime, timezone

import asyncpg
import httpx

from trek.config import database_url

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ohlcv] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

BIRDEYE_BASE = "https://public-api.birdeye.so"
SOL_MINT = "So11111111111111111111111111111111111111112"
DEFAULT_PAIR = "SOL/USDC"

RESOLUTION_MAP = {
    "1m": "1m",
    "1h": "1H",
}

UPSERT_SQL = """
INSERT INTO ohlcv_data (timestamp, pair, resolution, open, high, low, close, volume)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (timestamp, pair, resolution) DO NOTHING
"""

UPSERT_RETURNING_SQL = """
INSERT INTO ohlcv_data (timestamp, pair, resolution, open, high, low, close, volume)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (timestamp, pair, resolution) DO NOTHING
RETURNING 1
"""

LATEST_TIMESTAMP_SQL = """
SELECT MAX(timestamp) FROM ohlcv_data
WHERE pair = $1 AND resolution = $2
"""

MAX_CHUNK_SECONDS = 89 * 86400
RATE_LIMIT_DELAY = 1.0
MAX_RETRIES = 3


def _birdeye_headers() -> dict[str, str]:
    key = os.environ.get("BIRDEYE_API_KEY", "")
    if not key:
        raise RuntimeError("BIRDEYE_API_KEY environment variable is required")
    return {
        "X-API-KEY": key,
        "x-chain": "solana",
    }


async def _fetch_ohlcv(
    client: httpx.AsyncClient,
    from_ts: int,
    to_ts: int,
    resolution: str,
) -> list[dict]:
    birdeye_type = RESOLUTION_MAP.get(resolution)
    if birdeye_type is None:
        raise ValueError(f"Unsupported resolution: {resolution}")

    params = {
        "address": SOL_MINT,
        "type": birdeye_type,
        "time_from": str(from_ts),
        "time_to": str(to_ts),
    }
    last_exc: Exception | None = None
    for attempt in range(MAX_RETRIES):
        try:
            resp = await client.get(
                f"{BIRDEYE_BASE}/defi/ohlcv",
                params=params,
                headers=_birdeye_headers(),
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("success"):
                raise RuntimeError(f"Birdeye API error: {data}")
            return data.get("data", {}).get("items", [])
        except httpx.HTTPStatusError as exc:
            last_exc = exc
            if exc.response.status_code in (429, 500, 502, 503, 504):
                delay = 2 ** (attempt + 1)
                log.warning(
                    "Birdeye %d for %d→%d, retry %d/%d in %ds",
                    exc.response.status_code, from_ts, to_ts,
                    attempt + 1, MAX_RETRIES, delay,
                )
                await asyncio.sleep(delay)
            else:
                raise
        except httpx.TransportError as exc:
            last_exc = exc
            delay = 2 ** (attempt + 1)
            log.warning(
                "Birdeye transport error for %d→%d, retry %d/%d in %ds: %s",
                from_ts, to_ts, attempt + 1, MAX_RETRIES, delay, exc,
            )
            await asyncio.sleep(delay)
    raise last_exc  # type: ignore[misc]


def _items_to_rows(items: list[dict], resolution: str) -> list[tuple]:
    rows = []
    for item in items:
        ts = datetime.fromtimestamp(item["unixTime"], tz=timezone.utc)
        rows.append((
            ts,
            DEFAULT_PAIR,
            resolution,
            float(item["o"]),
            float(item["h"]),
            float(item["l"]),
            float(item["c"]),
            float(item["v"]),
        ))
    return rows


async def _upsert_batch(pool: asyncpg.Pool, rows: list[tuple]) -> int:
    if not rows:
        return 0
    inserted = 0
    async with pool.acquire() as conn:
        for row in rows:
            result = await conn.fetch(UPSERT_RETURNING_SQL, *row)
            inserted += len(result)
    return inserted


async def backfill(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    resolution: str = "1h",
    days: int = 90,
) -> int:
    now = int(time.time())
    start = now - (days * 86400)

    if resolution == "1m":
        chunk_seconds = 86400
    else:
        chunk_seconds = MAX_CHUNK_SECONDS

    total = 0
    chunk_start = start

    while chunk_start < now:
        chunk_end = min(chunk_start + chunk_seconds, now)
        log.info(
            "Fetching %s chunk %s → %s",
            resolution,
            datetime.fromtimestamp(chunk_start, tz=timezone.utc).isoformat(),
            datetime.fromtimestamp(chunk_end, tz=timezone.utc).isoformat(),
        )

        try:
            items = await _fetch_ohlcv(client, chunk_start, chunk_end, resolution)
        except Exception:
            log.exception(
                "Failed to fetch chunk %s → %s after %d retries — gap in data",
                datetime.fromtimestamp(chunk_start, tz=timezone.utc).isoformat(),
                datetime.fromtimestamp(chunk_end, tz=timezone.utc).isoformat(),
                MAX_RETRIES,
            )
            chunk_start = chunk_end
            await asyncio.sleep(RATE_LIMIT_DELAY)
            continue

        rows = _items_to_rows(items, resolution)
        inserted = await _upsert_batch(pool, rows)
        total += inserted
        log.info("Upserted %d rows (%d total)", inserted, total)

        chunk_start = chunk_end
        await asyncio.sleep(RATE_LIMIT_DELAY)

    return total


async def fetch_latest(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    resolution: str = "1h",
) -> int:
    async with pool.acquire() as conn:
        latest = await conn.fetchval(LATEST_TIMESTAMP_SQL, DEFAULT_PAIR, resolution)

    if latest is None:
        log.info("No existing data for %s %s — running full backfill", DEFAULT_PAIR, resolution)
        return await backfill(pool, client, resolution, days=90)

    from_ts = int(latest.timestamp())
    to_ts = int(time.time())

    if to_ts - from_ts < 60:
        log.info("Data already up to date for %s %s", DEFAULT_PAIR, resolution)
        return 0

    log.info(
        "Incremental fetch %s from %s",
        resolution,
        latest.isoformat(),
    )

    items = await _fetch_ohlcv(client, from_ts, to_ts, resolution)
    rows = _items_to_rows(items, resolution)
    return await _upsert_batch(pool, rows)


async def run_backfill(days: int, resolution: str) -> None:
    dsn = database_url()
    if not dsn:
        log.error("DATABASE_URL not set")
        return

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    async with httpx.AsyncClient() as client:
        try:
            total = await backfill(pool, client, resolution, days)
            log.info("Backfill complete: %d rows for %s %s", total, DEFAULT_PAIR, resolution)
        finally:
            await pool.close()


async def run_update(resolution: str) -> None:
    dsn = database_url()
    if not dsn:
        log.error("DATABASE_URL not set")
        return

    pool = await asyncpg.create_pool(dsn, min_size=1, max_size=3)
    async with httpx.AsyncClient() as client:
        try:
            count = await fetch_latest(pool, client, resolution)
            log.info("Update complete: %d new rows for %s %s", count, DEFAULT_PAIR, resolution)
        finally:
            await pool.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="OHLCV data fetcher")
    sub = parser.add_subparsers(dest="command", required=True)

    bp = sub.add_parser("backfill", help="Backfill historical data")
    bp.add_argument("--days", type=int, default=90)
    bp.add_argument("--resolution", default="1h", choices=["1m", "1h"])

    up = sub.add_parser("update", help="Incremental update")
    up.add_argument("--resolution", default="1h", choices=["1m", "1h"])

    args = parser.parse_args()

    if args.command == "backfill":
        asyncio.run(run_backfill(args.days, args.resolution))
    elif args.command == "update":
        asyncio.run(run_update(args.resolution))


if __name__ == "__main__":
    main()
