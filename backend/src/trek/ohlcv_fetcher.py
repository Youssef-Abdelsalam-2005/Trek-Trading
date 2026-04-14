"""OHLCV data fetcher — pulls SOL/USDC candles from CoinGecko and stores them in TimescaleDB.

CoinGecko's /coins/{id}/market_chart/range endpoint returns price + volume data
points at granularity determined by the requested range:
  - range ≤ 1 day  → ~5-minute intervals
  - range ≤ 90 days → hourly intervals
  - range > 90 days → daily intervals

We construct OHLCV candles from adjacent price points. The open/high/low/close
values are derived from the same price point (no intra-period aggregation),
which is adequate for vectorbt backtesting that primarily uses close prices.
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

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [ohlcv] %(levelname)s %(message)s",
)
log = logging.getLogger(__name__)

COINGECKO_BASE = "https://api.coingecko.com/api/v3"
COIN_ID = "solana"
VS_CURRENCY = "usd"
DEFAULT_PAIR = "SOL/USDC"

UPSERT_SQL = """
INSERT INTO ohlcv_data (timestamp, pair, resolution, open, high, low, close, volume)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
ON CONFLICT (timestamp, pair, resolution) DO NOTHING
"""

LATEST_TIMESTAMP_SQL = """
SELECT MAX(timestamp) FROM ohlcv_data
WHERE pair = $1 AND resolution = $2
"""

MAX_CHUNK_DAYS = 89
RATE_LIMIT_DELAY = 2.1


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


def _coingecko_headers() -> dict[str, str]:
    key = os.environ.get("COINGECKO_API_KEY", "")
    if key:
        return {"x-cg-demo-api-key": key}
    return {}


async def _fetch_market_chart_range(
    client: httpx.AsyncClient,
    from_ts: int,
    to_ts: int,
) -> tuple[list[list], list[list]]:
    params = {
        "vs_currency": VS_CURRENCY,
        "from": str(from_ts),
        "to": str(to_ts),
    }
    resp = await client.get(
        f"{COINGECKO_BASE}/coins/{COIN_ID}/market_chart/range",
        params=params,
        headers=_coingecko_headers(),
        timeout=30.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data.get("prices", []), data.get("total_volumes", [])


def _build_candles(
    prices: list[list],
    volumes: list[list],
    resolution: str,
) -> list[tuple]:
    volume_map: dict[int, float] = {}
    for ts_ms, vol in volumes:
        volume_map[ts_ms] = vol

    rows = []
    for i, (ts_ms, price) in enumerate(prices):
        ts = datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc)
        vol = volume_map.get(ts_ms, 0.0)

        if i > 0:
            prev_price = prices[i - 1][1]
            o = prev_price
            h = max(prev_price, price)
            l = min(prev_price, price)
        else:
            o = price
            h = price
            l = price

        rows.append((ts, DEFAULT_PAIR, resolution, o, h, l, price, vol))
    return rows


async def _upsert_batch(pool: asyncpg.Pool, rows: list[tuple]) -> int:
    if not rows:
        return 0
    async with pool.acquire() as conn:
        await conn.executemany(UPSERT_SQL, rows)
    return len(rows)


async def backfill(
    pool: asyncpg.Pool,
    client: httpx.AsyncClient,
    resolution: str = "1h",
    days: int = 90,
) -> int:
    now = int(time.time())
    start = now - (days * 86400)

    if resolution == "1m":
        chunk_days = 1
    else:
        chunk_days = MAX_CHUNK_DAYS

    total = 0
    chunk_start = start

    while chunk_start < now:
        chunk_end = min(chunk_start + chunk_days * 86400, now)
        log.info(
            "Fetching %s chunk %s → %s",
            resolution,
            datetime.fromtimestamp(chunk_start, tz=timezone.utc).isoformat(),
            datetime.fromtimestamp(chunk_end, tz=timezone.utc).isoformat(),
        )

        prices, volumes = await _fetch_market_chart_range(
            client, chunk_start, chunk_end
        )
        rows = _build_candles(prices, volumes, resolution)
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

    prices, volumes = await _fetch_market_chart_range(client, from_ts, to_ts)
    rows = _build_candles(prices, volumes, resolution)
    return await _upsert_batch(pool, rows)


async def run_backfill(days: int, resolution: str) -> None:
    dsn = _database_url()
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
    dsn = _database_url()
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
