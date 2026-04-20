from __future__ import annotations

import asyncio
import json
import os

import asyncpg
from fastapi import FastAPI, Query
from fastapi.responses import StreamingResponse

from trek.services.wallet_tracker import WALLET_ALERT_CHANNEL

app = FastAPI(title="Trek Trading API")

_pool: asyncpg.Pool | None = None


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql+asyncpg://"):
        url = url.replace("postgresql+asyncpg://", "postgresql://", 1)
    return url


@app.on_event("startup")
async def _startup() -> None:
    global _pool
    dsn = _database_url()
    if dsn:
        _pool = await asyncpg.create_pool(dsn, min_size=1, max_size=5)


@app.on_event("shutdown")
async def _shutdown() -> None:
    if _pool is not None:
        await _pool.close()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.get("/wallet/balance")
async def wallet_balance() -> dict:
    if _pool is None:
        return {"error": "database not configured"}
    wallet_address = os.environ.get("HOT_WALLET_ADDRESS", "")
    if not wallet_address:
        return {"error": "HOT_WALLET_ADDRESS not configured"}

    async with _pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT id, wallet_address, sol_balance, usdc_balance, snapshot_at, created_at, updated_at "
            "FROM wallet_state WHERE wallet_address = $1 ORDER BY snapshot_at DESC LIMIT 1",
            wallet_address,
        )
    if row is None:
        return {"error": "no balance data yet"}
    return dict(row)


@app.get("/wallet/balance/history")
async def wallet_balance_history(limit: int = Query(default=288, ge=1, le=2000)) -> list[dict]:
    if _pool is None:
        return []
    wallet_address = os.environ.get("HOT_WALLET_ADDRESS", "")
    if not wallet_address:
        return []

    async with _pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id, wallet_address, sol_balance, usdc_balance, snapshot_at, created_at, updated_at "
            "FROM wallet_state WHERE wallet_address = $1 ORDER BY snapshot_at DESC LIMIT $2",
            wallet_address, limit,
        )
    return [dict(r) for r in rows]


async def _sse_generator(wallet_address: str):
    dsn = _database_url()
    if not dsn:
        return

    conn = await asyncpg.connect(dsn)
    queue: asyncio.Queue[str] = asyncio.Queue()

    def _on_notify(conn, pid, channel, payload):
        queue.put_nowait(payload)

    await conn.add_listener(WALLET_ALERT_CHANNEL, _on_notify)

    try:
        yield f"data: {json.dumps({'type': 'connected', 'wallet_address': wallet_address})}\n\n"
        while True:
            try:
                payload = await asyncio.wait_for(queue.get(), timeout=30.0)
                yield f"data: {payload}\n\n"
            except asyncio.TimeoutError:
                yield ": keepalive\n\n"
    finally:
        await conn.remove_listener(WALLET_ALERT_CHANNEL, _on_notify)
        await conn.close()


@app.get("/wallet/alerts")
async def wallet_alerts() -> StreamingResponse:
    wallet_address = os.environ.get("HOT_WALLET_ADDRESS", "")
    return StreamingResponse(
        _sse_generator(wallet_address),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
