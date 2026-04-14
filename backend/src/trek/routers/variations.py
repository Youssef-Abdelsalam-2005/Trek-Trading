from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.enums import StrategyStatus
from backend.app.models.live_deployment import LiveDeployment
from backend.app.models.risk_config import RiskConfig
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.models.wallet_state import WalletState
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
                    RiskConfig.label == "global",
                    RiskConfig.is_active.is_(True),
                )
            )
        ).scalar_one_or_none()
        if risk_config is None:
            raise HTTPException(
                status_code=422,
                detail="No active global risk configuration found. Configure risk settings before promoting.",
            )

        live_count_result = await session.execute(
            select(func.count()).select_from(StrategyVariation).where(
                StrategyVariation.status == StrategyStatus.LIVE
            )
        )
        live_count = live_count_result.scalar_one()
        if live_count >= risk_config.max_concurrent_live:
            raise HTTPException(
                status_code=422,
                detail=f"Max concurrent live strategies reached ({risk_config.max_concurrent_live}). "
                f"Halt or kill an existing live strategy before promoting.",
            )

        wallet = (
            await session.execute(
                select(WalletState).order_by(WalletState.snapshot_at.desc()).limit(1)
            )
        ).scalar_one_or_none()
        if wallet is None:
            raise HTTPException(
                status_code=422,
                detail="No wallet state available. Ensure wallet balance is synced before promoting.",
            )

        required_balance_usd = risk_config.max_position_size_usd
        available_balance_usd = wallet.sol_balance + wallet.usdc_balance
        if available_balance_usd < required_balance_usd:
            raise HTTPException(
                status_code=422,
                detail=f"Insufficient wallet balance. "
                f"Available: ${available_balance_usd:.2f}, "
                f"required (max_position_size_usd): ${required_balance_usd:.2f}",
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
