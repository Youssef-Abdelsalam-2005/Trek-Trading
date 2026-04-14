from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any

import asyncpg
import httpx

log = logging.getLogger(__name__)

USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
LAMPORTS_PER_SOL = 1_000_000_000
USDC_DECIMALS = 1_000_000
WALLET_ALERT_CHANNEL = "wallet_alert"

INSERT_SNAPSHOT_SQL = """
INSERT INTO wallet_state (id, wallet_address, sol_balance, usdc_balance, snapshot_at, created_at, updated_at)
VALUES ($1, $2, $3, $4, $5, now(), now())
"""

LATEST_SNAPSHOT_SQL = """
SELECT id, wallet_address, sol_balance, usdc_balance, snapshot_at, created_at, updated_at
FROM wallet_state
WHERE wallet_address = $1
ORDER BY snapshot_at DESC
LIMIT 1
"""

HISTORY_SQL = """
SELECT id, wallet_address, sol_balance, usdc_balance, snapshot_at, created_at, updated_at
FROM wallet_state
WHERE wallet_address = $1
ORDER BY snapshot_at DESC
LIMIT $2
"""


class WalletTracker:
    def __init__(
        self,
        pool: asyncpg.Pool,
        rpc_url: str,
        wallet_address: str,
        low_balance_threshold_usd: float = 100.0,
    ):
        self._pool = pool
        self._rpc_url = rpc_url
        self._wallet_address = wallet_address
        self._threshold = low_balance_threshold_usd

    async def _rpc_call(self, client: httpx.AsyncClient, method: str, params: list[Any]) -> Any:
        resp = await client.post(
            self._rpc_url,
            json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params},
            timeout=15.0,
        )
        resp.raise_for_status()
        body = resp.json()
        if "error" in body:
            raise RuntimeError(f"Solana RPC error: {body['error']}")
        return body["result"]

    async def fetch_balances(self) -> tuple[float, float]:
        async with httpx.AsyncClient() as client:
            sol_result = await self._rpc_call(client, "getBalance", [self._wallet_address])
            sol_balance = sol_result["value"] / LAMPORTS_PER_SOL

            usdc_result = await self._rpc_call(
                client,
                "getTokenAccountsByOwner",
                [
                    self._wallet_address,
                    {"mint": USDC_MINT},
                    {"encoding": "jsonParsed"},
                ],
            )

            usdc_balance = 0.0
            accounts = usdc_result.get("value", [])
            for account in accounts:
                token_amount = (
                    account.get("account", {})
                    .get("data", {})
                    .get("parsed", {})
                    .get("info", {})
                    .get("tokenAmount", {})
                )
                raw_amount = int(token_amount.get("amount", "0"))
                usdc_balance += raw_amount / USDC_DECIMALS

        return sol_balance, usdc_balance

    async def snapshot(self) -> dict[str, Any]:
        sol_balance, usdc_balance = await self.fetch_balances()
        now = datetime.now(timezone.utc)
        snapshot_id = uuid.uuid4()

        async with self._pool.acquire() as conn:
            await conn.execute(
                INSERT_SNAPSHOT_SQL,
                snapshot_id, self._wallet_address, sol_balance, usdc_balance, now,
            )

        log.info(
            "wallet snapshot: address=%s SOL=%.4f USDC=%.2f",
            self._wallet_address, sol_balance, usdc_balance,
        )

        if usdc_balance < self._threshold:
            await self._emit_low_balance_alert(sol_balance, usdc_balance)

        return {
            "id": str(snapshot_id),
            "wallet_address": self._wallet_address,
            "sol_balance": sol_balance,
            "usdc_balance": usdc_balance,
            "snapshot_at": now.isoformat(),
        }

    async def _emit_low_balance_alert(self, sol_balance: float, usdc_balance: float) -> None:
        alert = json.dumps({
            "type": "low_balance",
            "wallet_address": self._wallet_address,
            "sol_balance": sol_balance,
            "usdc_balance": usdc_balance,
            "threshold_usd": self._threshold,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        async with self._pool.acquire() as conn:
            await conn.execute(f"SELECT pg_notify('{WALLET_ALERT_CHANNEL}', $1)", alert)
        log.warning(
            "LOW BALANCE ALERT: USDC=%.2f below threshold=%.2f",
            usdc_balance, self._threshold,
        )

    async def get_latest(self) -> dict[str, Any] | None:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(LATEST_SNAPSHOT_SQL, self._wallet_address)
            return dict(row) if row else None

    async def get_history(self, limit: int = 288) -> list[dict[str, Any]]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(HISTORY_SQL, self._wallet_address, limit)
            return [dict(r) for r in rows]
