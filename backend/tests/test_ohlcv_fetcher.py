"""Tests for the OHLCV data fetcher.

These tests mock the Birdeye API and use a real PostgreSQL+TimescaleDB
database via the docker-compose stack (must be running).
"""

from __future__ import annotations

import asyncio
import os
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
    _fetch_ohlcv,
    _items_to_rows,
    _upsert_batch,
    backfill,
    fetch_latest,
)

SAMPLE_ITEMS = [
    {"unixTime": 1700000000, "o": 100.0, "h": 101.0, "l": 99.0, "c": 100.5, "v": 5000000.0},
    {"unixTime": 1700003600, "o": 100.5, "h": 102.0, "l": 100.0, "c": 101.5, "v": 6000000.0},
    {"unixTime": 1700007200, "o": 101.5, "h": 101.5, "l": 99.0, "c": 99.8, "v": 4500000.0},
    {"unixTime": 1700010800, "o": 99.8, "h": 102.5, "l": 99.5, "c": 102.3, "v": 7000000.0},
]


class TestItemsToRows:
    def test_builds_correct_number_of_rows(self):
        rows = _items_to_rows(SAMPLE_ITEMS, "1h")
        assert len(rows) == 4

    def test_ohlcv_values_preserved(self):
        rows = _items_to_rows(SAMPLE_ITEMS, "1h")
        ts, pair, res, o, h, l, c, v = rows[0]
        assert o == 100.0
        assert h == 101.0
        assert l == 99.0
        assert c == 100.5
        assert v == 5000000.0

    def test_timestamps_are_utc(self):
        rows = _items_to_rows(SAMPLE_ITEMS, "1h")
        for ts, *_ in rows:
            assert ts.tzinfo == timezone.utc

    def test_pair_and_resolution_set(self):
        rows = _items_to_rows(SAMPLE_ITEMS, "1h")
        for _, pair, res, *_ in rows:
            assert pair == DEFAULT_PAIR
            assert res == "1h"

    def test_empty_input(self):
        rows = _items_to_rows([], "1h")
        assert rows == []

    def test_second_candle_values(self):
        rows = _items_to_rows(SAMPLE_ITEMS, "1h")
        ts, pair, res, o, h, l, c, v = rows[1]
        assert o == 100.5
        assert h == 102.0
        assert l == 100.0
        assert c == 101.5
        assert v == 6000000.0

    def test_unix_timestamp_conversion(self):
        rows = _items_to_rows(SAMPLE_ITEMS, "1h")
        expected = datetime.fromtimestamp(1700000000, tz=timezone.utc)
        assert rows[0][0] == expected


@patch.dict(os.environ, {"BIRDEYE_API_KEY": "test-key"})
class TestFetchOhlcvRetry:
    @pytest.mark.asyncio
    async def test_retries_on_429(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = AsyncMock()
        error_resp.status_code = 429
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "rate limited", request=AsyncMock(), response=error_resp
        )
        ok_resp = AsyncMock()
        ok_resp.raise_for_status = lambda: None
        ok_resp.json.return_value = {
            "success": True,
            "data": {"items": SAMPLE_ITEMS},
        }
        mock_client.get.side_effect = [error_resp, ok_resp]

        with patch("trek.ohlcv_fetcher.asyncio.sleep", new_callable=AsyncMock):
            items = await _fetch_ohlcv(mock_client, 1000, 2000, "1h")
        assert len(items) == 4
        assert mock_client.get.call_count == 2

    @pytest.mark.asyncio
    async def test_raises_on_non_retryable_status(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        error_resp = AsyncMock()
        error_resp.status_code = 403
        error_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "forbidden", request=AsyncMock(), response=error_resp
        )
        mock_client.get.return_value = error_resp

        with pytest.raises(httpx.HTTPStatusError):
            await _fetch_ohlcv(mock_client, 1000, 2000, "1h")
        assert mock_client.get.call_count == 1

    @pytest.mark.asyncio
    async def test_raises_without_api_key(self):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(RuntimeError, match="BIRDEYE_API_KEY"):
                await _fetch_ohlcv(mock_client, 1000, 2000, "1h")


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

        with patch("trek.ohlcv_fetcher._fetch_ohlcv", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = SAMPLE_ITEMS
            total = await backfill(pool, mock_client, "test_1h", days=1)
            assert total == 4
            mock_fetch.assert_called()

    @pytest.mark.asyncio
    async def test_fetch_latest_no_data_triggers_backfill(self, pool):
        mock_client = AsyncMock(spec=httpx.AsyncClient)
        mock_resp = AsyncMock()
        mock_resp.json.return_value = {
            "success": True,
            "data": {"items": SAMPLE_ITEMS},
        }
        mock_resp.raise_for_status = lambda: None
        mock_client.get.return_value = mock_resp

        with patch("trek.ohlcv_fetcher.backfill", new_callable=AsyncMock) as mock_bf:
            mock_bf.return_value = 100
            count = await fetch_latest(pool, mock_client, "test_1h")
            assert count == 100
            mock_bf.assert_called_once()
