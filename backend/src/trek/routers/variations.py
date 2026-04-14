from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.enums import StrategyStatus
from backend.app.models.live_deployment import LiveDeployment
from backend.app.models.risk_config import RiskConfig
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.schemas.strategy_variation import StrategyVariationResponse
from trek.database import get_session
from trek.sse import broadcast

router = APIRouter(prefix="/api/variations", tags=["variations"])


@router.post("/{variation_id}/promote", response_model=StrategyVariationResponse)
async def promote_to_live(
    variation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> StrategyVariationResponse:
    async with session.begin():
        result = await session.execute(
            select(StrategyVariation)
            .where(StrategyVariation.id == variation_id)
            .with_for_update()
        )
        variation = result.scalar_one_or_none()
        if variation is None:
            raise HTTPException(status_code=404, detail="Variation not found")

        if variation.status != StrategyStatus.PAPER_PASSED:
            raise HTTPException(
                status_code=409,
                detail=f"Cannot promote: variation is in '{variation.status.value}' state, expected 'paper_passed'",
            )

        risk_config = (
            await session.execute(
                select(RiskConfig).where(
                    RiskConfig.experiment_id.is_(None),
                )
            )
        ).scalar_one_or_none()

        max_concurrent = (
            risk_config.max_concurrent_live
            if risk_config and risk_config.max_concurrent_live is not None
            else RiskConfig.GLOBAL_DEFAULTS["max_concurrent_live"]
        )

        live_count_result = await session.execute(
            select(func.count()).select_from(StrategyVariation).where(
                StrategyVariation.status == StrategyStatus.LIVE
            )
        )
        live_count = live_count_result.scalar_one()
        if live_count >= max_concurrent:
            raise HTTPException(
                status_code=422,
                detail=f"Max concurrent live strategies reached ({max_concurrent}). "
                f"Halt or kill an existing live strategy before promoting.",
            )

        variation.transition_to(StrategyStatus.LIVE)

        now = datetime.now(timezone.utc)
        deployment = LiveDeployment(
            variation_id=variation.id,
            started_at=now,
        )
        session.add(deployment)

    await session.refresh(variation)

    broadcast(
        "strategy_promoted",
        {
            "variation_id": str(variation.id),
            "experiment_id": str(variation.experiment_id),
            "status": variation.status.value,
        },
    )

    return StrategyVariationResponse.model_validate(variation)
