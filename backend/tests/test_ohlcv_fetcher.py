"""Tests for the OHLCV data fetcher.

These tests mock the CoinGecko API and use a real PostgreSQL+TimescaleDB
database via the docker-compose stack (must be running).
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

try:
    import asyncpg
    import httpx
except ImportError:
    pytest.skip("asyncpg/httpx not installed", allow_module_level=True)

from trek.ohlcv_fetcher import (
    DEFAULT_PAIR,
    UPSERT_SQL,
    _build_candles,
    _fetch_market_chart_range,
    _upsert_batch,
    backfill,
    fetch_latest,
)

SAMPLE_PRICES = [
    [1700000000000, 100.0],
    [1700003600000, 101.5],
    [1700007200000, 99.8],
    [1700010800000, 102.3],
]

SAMPLE_VOLUMES = [
    [1700000000000, 5000000.0],
    [1700003600000, 6000000.0],
    [1700007200000, 4500000.0],
    [1700010800000, 7000000.0],
]


class TestBuildCandles:
    def test_builds_correct_number_of_rows(self):
        rows = _build_candles(SAMPLE_PRICES, SAMPLE_VOLUMES, "1h")
        assert len(rows) == 4

    def test_first_candle_open_equals_close(self):
        rows = _build_candles(SAMPLE_PRICES, SAMPLE_VOLUMES, "1h")
        ts, pair, res, o, h, l, c, v = rows[0]
        assert o == c == 100.0

    def test_subsequent_candle_open_is_previous_close(self):
        rows = _build_candles(SAMPLE_PRICES, SAMPLE_VOLUMES, "1h")
        _, _, _, _, _, _, c0, _ = rows[0]
        _, _, _, o1, _, _, c1, _ = rows[1]
        assert o1 == c0
        assert c1 == 101.5

    def test_high_low_computed_correctly(self):
        rows = _build_candles(SAMPLE_PRICES, SAMPLE_VOLUMES, "1h")
        _, _, _, o, h, l, c, _ = rows[2]
        assert h == max(101.5, 99.8)
        assert l == min(101.5, 99.8)

    def test_volume_mapped(self):
        rows = _build_candles(SAMPLE_PRICES, SAMPLE_VOLUMES, "1h")
        assert rows[0][7] == 5000000.0
        assert rows[1][7] == 6000000.0

    def test_timestamps_are_utc(self):
        rows = _build_candles(SAMPLE_PRICES, SAMPLE_VOLUMES, "1h")
        for ts, *_ in rows:
            assert ts.tzinfo == timezone.utc

    def test_pair_and_resolution_set(self):
        rows = _build_candles(SAMPLE_PRICES, SAMPLE_VOLUMES, "1h")
        for _, pair, res, *_ in rows:
            assert pair == DEFAULT_PAIR
            assert res == "1h"

    def test_empty_input(self):
        rows = _build_candles([], [], "1h")
        assert rows == []


DB_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://trek:trek_dev@localhost:5433/trek",
)


def _db_available() -> bool:
    try:
        asyncio.run(asyncpg.connect(DB_URL))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(),
    reason="TimescaleDB not available at TEST_DATABASE_URL",
)


@needs_db
class TestUpsertIdempotency:
    @pytest.fixture
    async def pool(self):
        pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM ohlcv_data WHERE pair = 'TEST/USD'")
        yield pool
        async with pool.acquire() as conn:
            await conn.execute("DELETE FROM ohlcv_data WHERE pair = 'TEST/USD'")
        await pool.close()

    @pytest.mark.asyncio
    async def test_upsert_is_idempotent(self, pool):
        ts = datetime(2025, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        row = (ts, "TEST/USD", "1h", 100.0, 101.0, 99.0, 100.5, 1000.0)

        count1 = await _upsert_batch(pool, [row])
        assert count1 == 1

        count2 = await _upsert_batch(pool, [row])
        assert count2 == 0

        async with pool.acquire() as conn:
            result = await conn.fetchval(
                "SELECT COUNT(*) FROM ohlcv_data WHERE pair = 'TEST/USD'"
            )
        assert result == 1

    @pytest.mark.asyncio
    async def test_date_range_query(self, pool):
        rows = [
            (datetime(2025, 1, 1, h, 0, 0, tzinfo=timezone.utc), "TEST/USD", "1h",
             100.0 + h, 101.0 + h, 99.0 + h, 100.5 + h, 1000.0 * h)
            for h in range(24)
        ]
        await _upsert_batch(pool, rows)

        async with pool.acquire() as conn:
            result = await conn.fetch(
                "SELECT * FROM ohlcv_data WHERE pair = 'TEST/USD' "
                "AND timestamp >= $1 AND timestamp < $2 ORDER BY timestamp",
                datetime(2025, 1, 1, 6, 0, 0, tzinfo=timezone.utc),
                datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc),
            )
        assert len(result) == 6


@needs_db
class TestBackfillAndUpdate:
    @pytest.fixture
    async def pool(self):
        pool = await asyncpg.create_pool(DB_URL, min_size=1, max_size=2)
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM ohlcv_data WHERE pair = $1 AND resolution = $2",
                DEFAULT_PAIR, "test_1h",
            )
        yield pool
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM ohlcv_data WHERE pair = $1 AND resolution = $2",
                DEFAULT_PAIR, "test_1h",
            )
        await pool.close()

    @pytest.mark.asyncio
    async def test_backfill_calls_api_and_inserts(self, pool):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock()
        mock_resp.json.return_value = {
            "prices": SAMPLE_PRICES,
            "total_volumes": SAMPLE_VOLUMES,
        }
        mock_resp.raise_for_status = lambda: None
        mock_client.get.return_value = mock_resp

        total = await backfill(pool, mock_client, "test_1h", days=1)
        assert total == 4
        assert mock_client.get.called

    @pytest.mark.asyncio
    async def test_fetch_latest_no_data_triggers_backfill(self, pool):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock()
        mock_resp.json.return_value = {
            "prices": SAMPLE_PRICES,
            "total_volumes": SAMPLE_VOLUMES,
        }
        mock_resp.raise_for_status = lambda: None
        mock_client.get.return_value = mock_resp

        with patch("trek.ohlcv_fetcher.backfill", new_callable=AsyncMock) as mock_bf:
            mock_bf.return_value = 100
            count = await fetch_latest(pool, mock_client, "test_1h")
            assert count == 100
            mock_bf.assert_called_once()


class TestHttpRetry:
    @pytest.mark.asyncio
    async def test_retries_on_429_then_succeeds(self):
        error_resp = httpx.Response(429, request=httpx.Request("GET", "http://test"))
        ok_resp = AsyncMock()
        ok_resp.raise_for_status = lambda: None
        ok_resp.json.return_value = {"prices": SAMPLE_PRICES, "total_volumes": SAMPLE_VOLUMES}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            httpx.HTTPStatusError("rate limited", request=error_resp.request, response=error_resp),
            ok_resp,
        ]

        with patch("trek.ohlcv_fetcher.asyncio.sleep", new_callable=AsyncMock):
            prices, volumes = await _fetch_market_chart_range(client, 1000, 2000)

        assert len(prices) == 4
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_retries_on_500_then_succeeds(self):
        error_resp = httpx.Response(500, request=httpx.Request("GET", "http://test"))
        ok_resp = AsyncMock()
        ok_resp.raise_for_status = lambda: None
        ok_resp.json.return_value = {"prices": SAMPLE_PRICES, "total_volumes": SAMPLE_VOLUMES}

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [
            httpx.HTTPStatusError("server error", request=error_resp.request, response=error_resp),
            ok_resp,
        ]

        with patch("trek.ohlcv_fetcher.asyncio.sleep", new_callable=AsyncMock):
            prices, volumes = await _fetch_market_chart_range(client, 1000, 2000)

        assert len(prices) == 4
        assert client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        error_resp = httpx.Response(429, request=httpx.Request("GET", "http://test"))
        exc = httpx.HTTPStatusError("rate limited", request=error_resp.request, response=error_resp)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = [exc, exc, exc]

        with patch("trek.ohlcv_fetcher.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(httpx.HTTPStatusError):
                await _fetch_market_chart_range(client, 1000, 2000)

        assert client.get.call_count == 3

    @pytest.mark.asyncio
    async def test_does_not_retry_on_4xx(self):
        error_resp = httpx.Response(404, request=httpx.Request("GET", "http://test"))
        exc = httpx.HTTPStatusError("not found", request=error_resp.request, response=error_resp)

        client = AsyncMock(spec=httpx.AsyncClient)
        client.get.side_effect = exc

        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_market_chart_range(client, 1000, 2000)

        assert client.get.call_count == 1
