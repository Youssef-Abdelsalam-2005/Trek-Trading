from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

import asyncpg

log = logging.getLogger(__name__)

INSERT_TRADE_SQL = """
INSERT INTO trade (
    id, variation_id, paper_session_id, live_deployment_id,
    source, direction, status, pair,
    input_amount, output_amount, quoted_price, fill_price,
    price_impact_bps, fee_usd, slippage_bps, jito_tip_lamports,
    tx_signature, failure_reason, executed_at,
    created_at, updated_at
) VALUES (
    $1, $2, $3, $4,
    $5, $6, $7, $8,
    $9, $10, $11, $12,
    $13, $14, $15, $16,
    $17, $18, $19,
    now(), now()
)
RETURNING id;
"""

LIST_TRADES_SQL = """
SELECT
    t.id, t.variation_id, t.paper_session_id, t.live_deployment_id,
    t.source, t.direction, t.status, t.pair,
    t.input_amount, t.output_amount, t.quoted_price, t.fill_price,
    t.price_impact_bps, t.fee_usd, t.slippage_bps, t.jito_tip_lamports,
    t.tx_signature, t.failure_reason, t.executed_at,
    t.created_at, t.updated_at
FROM trade t
"""

COUNT_TRADES_SQL = """
SELECT count(*) FROM trade t
"""

JOIN_VARIATION = """
JOIN strategy_variation sv ON sv.id = t.variation_id
"""


class TradeLogger:
    def __init__(self, pool: asyncpg.Pool):
        self._pool = pool

    async def log_trade(
        self,
        *,
        variation_id: uuid.UUID,
        source: str,
        direction: str,
        status: str,
        input_amount: float,
        quoted_price: float,
        executed_at: datetime,
        paper_session_id: uuid.UUID | None = None,
        live_deployment_id: uuid.UUID | None = None,
        pair: str = "SOL/USDC",
        output_amount: float | None = None,
        fill_price: float | None = None,
        price_impact_bps: float | None = None,
        fee_usd: float | None = None,
        slippage_bps: float | None = None,
        jito_tip_lamports: int | None = None,
        tx_signature: str | None = None,
        failure_reason: str | None = None,
    ) -> uuid.UUID:
        trade_id = uuid.uuid4()
        async with self._pool.acquire() as conn:
            await conn.execute(
                INSERT_TRADE_SQL,
                trade_id,
                variation_id,
                paper_session_id,
                live_deployment_id,
                source,
                direction,
                status,
                pair,
                input_amount,
                output_amount,
                quoted_price,
                fill_price,
                price_impact_bps,
                fee_usd,
                slippage_bps,
                jito_tip_lamports,
                tx_signature,
                failure_reason,
                executed_at,
            )
        log.info(
            "logged trade %s variation=%s source=%s status=%s",
            trade_id, variation_id, source, status,
        )
        return trade_id

    async def list_trades(
        self,
        *,
        variation_id: uuid.UUID | None = None,
        experiment_id: uuid.UUID | None = None,
        source: str | None = None,
        status: str | None = None,
        start_date: datetime | None = None,
        end_date: datetime | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        conditions: list[str] = []
        params: list[Any] = []
        needs_join = experiment_id is not None

        idx = 1
        if variation_id is not None:
            conditions.append(f"t.variation_id = ${idx}")
            params.append(variation_id)
            idx += 1
        if experiment_id is not None:
            conditions.append(f"sv.experiment_id = ${idx}")
            params.append(experiment_id)
            idx += 1
        if source is not None:
            conditions.append(f"t.source = ${idx}")
            params.append(source)
            idx += 1
        if status is not None:
            conditions.append(f"t.status = ${idx}")
            params.append(status)
            idx += 1
        if start_date is not None:
            conditions.append(f"t.executed_at >= ${idx}")
            params.append(start_date)
            idx += 1
        if end_date is not None:
            conditions.append(f"t.executed_at < ${idx}")
            params.append(end_date)
            idx += 1

        join_clause = JOIN_VARIATION if needs_join else ""
        where_clause = " WHERE " + " AND ".join(conditions) if conditions else ""

        count_query = COUNT_TRADES_SQL + join_clause + where_clause
        list_query = (
            LIST_TRADES_SQL
            + join_clause
            + where_clause
            + f" ORDER BY t.executed_at DESC LIMIT ${idx} OFFSET ${idx + 1}"
        )
        params_with_pagination = params + [limit, offset]

        async with self._pool.acquire() as conn:
            total = await conn.fetchval(count_query, *params)
            rows = await conn.fetch(list_query, *params_with_pagination)

        return [dict(r) for r in rows], total
