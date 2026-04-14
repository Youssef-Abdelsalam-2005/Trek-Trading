from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.enums import TradeSource, TradeStatus
from backend.app.models.trade import Trade
from backend.app.schemas.trade import TradeResponse
from trek.db import get_session

router = APIRouter(prefix="/api/trades", tags=["trades"])


@router.get("", response_model=list[TradeResponse])
async def list_trades(
    variation_id: uuid.UUID | None = Query(default=None),
    experiment_id: uuid.UUID | None = Query(default=None),
    source: TradeSource | None = Query(default=None),
    status: TradeStatus | None = Query(default=None),
    start_date: datetime | None = Query(default=None),
    end_date: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[Trade]:
    stmt = select(Trade)

    if variation_id is not None:
        stmt = stmt.where(Trade.variation_id == variation_id)
    if experiment_id is not None:
        from backend.app.models.strategy_variation import StrategyVariation
        stmt = stmt.join(StrategyVariation, Trade.variation_id == StrategyVariation.id)
        stmt = stmt.where(StrategyVariation.experiment_id == experiment_id)
    if source is not None:
        stmt = stmt.where(Trade.source == source)
    if status is not None:
        stmt = stmt.where(Trade.status == status)
    if start_date is not None:
        stmt = stmt.where(Trade.executed_at >= start_date)
    if end_date is not None:
        stmt = stmt.where(Trade.executed_at < end_date)

    stmt = stmt.order_by(Trade.executed_at.desc()).limit(limit).offset(offset)
    result = await session.execute(stmt)
    return list(result.scalars().all())


@router.get("/strategy/{variation_id}", response_model=list[TradeResponse])
async def get_strategy_trades(
    variation_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> list[Trade]:
    stmt = (
        select(Trade)
        .where(Trade.variation_id == variation_id)
        .order_by(Trade.executed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())
