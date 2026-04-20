from __future__ import annotations

import uuid
from typing import Any

import asyncpg

ANCESTORS_SQL = """
WITH RECURSIVE lineage AS (
    SELECT id, parent_id, name, generation, status::text, code,
           llm_cost_usd, cumulative_llm_cost_usd, created_at,
           0 AS depth
    FROM strategy_variation
    WHERE id = $1

    UNION ALL

    SELECT sv.id, sv.parent_id, sv.name, sv.generation, sv.status::text, sv.code,
           sv.llm_cost_usd, sv.cumulative_llm_cost_usd, sv.created_at,
           l.depth + 1
    FROM strategy_variation sv
    JOIN lineage l ON sv.id = l.parent_id
)
SELECT id, parent_id, name, generation, status, code,
       llm_cost_usd, cumulative_llm_cost_usd, created_at, depth
FROM lineage
ORDER BY depth ASC;
"""

DESCENDANTS_SQL = """
WITH RECURSIVE lineage AS (
    SELECT id, parent_id, name, generation, status::text, code,
           llm_cost_usd, cumulative_llm_cost_usd, created_at,
           0 AS depth
    FROM strategy_variation
    WHERE id = $1

    UNION ALL

    SELECT sv.id, sv.parent_id, sv.name, sv.generation, sv.status::text, sv.code,
           sv.llm_cost_usd, sv.cumulative_llm_cost_usd, sv.created_at,
           l.depth + 1
    FROM strategy_variation sv
    JOIN lineage l ON sv.parent_id = l.id
)
SELECT id, parent_id, name, generation, status, code,
       llm_cost_usd, cumulative_llm_cost_usd, created_at, depth
FROM lineage
ORDER BY depth ASC;
"""


async def get_ancestors(
    pool: asyncpg.Pool, variation_id: uuid.UUID
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(ANCESTORS_SQL, variation_id)
        return [dict(r) for r in rows]


async def get_descendants(
    pool: asyncpg.Pool, variation_id: uuid.UUID
) -> list[dict[str, Any]]:
    async with pool.acquire() as conn:
        rows = await conn.fetch(DESCENDANTS_SQL, variation_id)
        return [dict(r) for r in rows]
