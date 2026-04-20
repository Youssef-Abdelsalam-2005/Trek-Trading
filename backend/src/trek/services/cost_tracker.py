from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.skeptic_audit import SkepticAudit
from backend.app.models.strategy_variation import StrategyVariation
from trek.services.llm_service import LLMUsage

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CostSummary:
    own_input_tokens: int
    own_output_tokens: int
    own_cost_usd: float
    skeptic_cost_usd: float
    cumulative_cost_usd: float


async def record_generation_cost(
    session: AsyncSession,
    variation_id: uuid.UUID,
    usage: LLMUsage,
) -> None:
    variation = await session.get(StrategyVariation, variation_id)
    if variation is None:
        raise ValueError(f"StrategyVariation {variation_id} not found")

    variation.llm_input_tokens += usage.input_tokens
    variation.llm_output_tokens += usage.output_tokens
    variation.llm_cost_usd += usage.cost_usd

    await _recompute_cumulative(session, variation)
    await session.flush()

    logger.info(
        "generation_cost_recorded",
        extra={
            "variation_id": str(variation_id),
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cost_usd": usage.cost_usd,
            "cumulative_cost_usd": variation.cumulative_llm_cost_usd,
        },
    )


async def record_skeptic_cost(
    session: AsyncSession,
    audit: SkepticAudit,
    variation_id: uuid.UUID,
) -> None:
    variation = await session.get(StrategyVariation, variation_id)
    if variation is None:
        raise ValueError(f"StrategyVariation {variation_id} not found")

    cost = audit.llm_cost_usd or 0.0
    variation.llm_input_tokens += audit.llm_input_tokens or 0
    variation.llm_output_tokens += audit.llm_output_tokens or 0
    variation.llm_cost_usd += cost

    await _recompute_cumulative(session, variation)
    await session.flush()

    logger.info(
        "skeptic_cost_recorded",
        extra={
            "variation_id": str(variation_id),
            "audit_stage": audit.stage,
            "cost_usd": cost,
            "cumulative_cost_usd": variation.cumulative_llm_cost_usd,
        },
    )


def compute_cumulative_cost(
    own_cost: float,
    parent_cumulative: float | None,
) -> float:
    return own_cost + (parent_cumulative or 0.0)


async def _recompute_cumulative(
    session: AsyncSession,
    variation: StrategyVariation,
) -> None:
    parent_cumulative = 0.0
    if variation.parent_id is not None:
        parent = await session.get(StrategyVariation, variation.parent_id)
        if parent is not None:
            parent_cumulative = parent.cumulative_llm_cost_usd

    variation.cumulative_llm_cost_usd = compute_cumulative_cost(
        variation.llm_cost_usd, parent_cumulative
    )

    await _propagate_to_descendants(session, variation)


async def _propagate_to_descendants(
    session: AsyncSession,
    variation: StrategyVariation,
) -> None:
    stmt = (
        select(StrategyVariation)
        .where(StrategyVariation.parent_id == variation.id)
        .options(selectinload(StrategyVariation.children))
    )
    result = await session.execute(stmt)
    children = result.scalars().all()

    for child in children:
        child.cumulative_llm_cost_usd = compute_cumulative_cost(
            child.llm_cost_usd, variation.cumulative_llm_cost_usd
        )
        await _propagate_to_descendants(session, child)


async def set_initial_cost(
    session: AsyncSession,
    variation: StrategyVariation,
    usage: LLMUsage,
) -> None:
    variation.llm_input_tokens = usage.input_tokens
    variation.llm_output_tokens = usage.output_tokens
    variation.llm_cost_usd = usage.cost_usd

    parent_cumulative = 0.0
    if variation.parent_id is not None:
        parent = await session.get(StrategyVariation, variation.parent_id)
        if parent is not None:
            parent_cumulative = parent.cumulative_llm_cost_usd

    variation.cumulative_llm_cost_usd = compute_cumulative_cost(
        usage.cost_usd, parent_cumulative
    )


async def get_cost_summary(
    session: AsyncSession,
    variation_id: uuid.UUID,
) -> CostSummary:
    variation = await session.get(StrategyVariation, variation_id)
    if variation is None:
        raise ValueError(f"StrategyVariation {variation_id} not found")

    stmt = select(SkepticAudit).where(SkepticAudit.variation_id == variation_id)
    result = await session.execute(stmt)
    audits = result.scalars().all()
    skeptic_cost = sum(a.llm_cost_usd or 0.0 for a in audits)

    return CostSummary(
        own_input_tokens=variation.llm_input_tokens,
        own_output_tokens=variation.llm_output_tokens,
        own_cost_usd=variation.llm_cost_usd,
        skeptic_cost_usd=skeptic_cost,
        cumulative_cost_usd=variation.cumulative_llm_cost_usd,
    )


async def get_lineage_costs(
    session: AsyncSession,
    variation_id: uuid.UUID,
) -> list[dict]:
    variation = await session.get(StrategyVariation, variation_id)
    if variation is None:
        raise ValueError(f"StrategyVariation {variation_id} not found")

    lineage: list[dict] = []
    current: StrategyVariation | None = variation
    while current is not None:
        lineage.append(
            {
                "id": str(current.id),
                "name": current.name,
                "generation": current.generation,
                "llm_cost_usd": current.llm_cost_usd,
                "cumulative_llm_cost_usd": current.cumulative_llm_cost_usd,
            }
        )
        if current.parent_id is not None:
            current = await session.get(StrategyVariation, current.parent_id)
        else:
            current = None

    lineage.reverse()
    return lineage
