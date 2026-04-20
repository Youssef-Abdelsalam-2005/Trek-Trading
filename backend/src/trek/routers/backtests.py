import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.backtest_run import BacktestRun
from backend.app.models.enums import TradeSource
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.models.trade import Trade
from backend.app.schemas.backtest_run import (
    BacktestRunDetail,
    BacktestRunResponse,
    BacktestRunSummary,
)
from backend.app.schemas.trade import TradeResponse
from trek.database import get_session

router = APIRouter(tags=["backtests"])


@router.get(
    "/api/variations/{variation_id}/backtests",
    response_model=list[BacktestRunSummary],
)
async def list_variation_backtests(
    variation_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[BacktestRunSummary]:
    variation = await session.get(StrategyVariation, variation_id)
    if variation is None:
        raise HTTPException(status_code=404, detail="Variation not found")

    stmt = (
        select(BacktestRun)
        .where(BacktestRun.variation_id == variation_id)
        .order_by(BacktestRun.created_at.desc())
    )
    result = await session.execute(stmt)
    runs = result.scalars().all()
    return [BacktestRunSummary.model_validate(run) for run in runs]


@router.get(
    "/api/backtests/{backtest_id}",
    response_model=BacktestRunDetail,
)
async def get_backtest(
    backtest_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> BacktestRunDetail:
    backtest = await session.get(BacktestRun, backtest_id)
    if backtest is None:
        raise HTTPException(status_code=404, detail="Backtest run not found")

    stmt = (
        select(Trade)
        .where(
            Trade.variation_id == backtest.variation_id,
            Trade.source == TradeSource.BACKTEST,
            Trade.executed_at >= backtest.start_date,
            Trade.executed_at <= backtest.end_date,
        )
        .order_by(Trade.executed_at.asc())
    )
    result = await session.execute(stmt)
    trades = result.scalars().all()

    backtest_data = BacktestRunResponse.model_validate(
        backtest, from_attributes=True
    ).model_dump()
    backtest_data["trades"] = [
        TradeResponse.model_validate(t, from_attributes=True) for t in trades
    ]
    return BacktestRunDetail.model_validate(backtest_data)
