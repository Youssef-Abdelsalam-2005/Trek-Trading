import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.app.models.experiment import Experiment
from backend.app.models.risk_config import RiskConfig
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.schemas.experiment import (
    ExperimentCreate,
    ExperimentResponse,
    ExperimentUpdate,
)
from trek.database import get_session

router = APIRouter(prefix="/api/experiments", tags=["experiments"])

RISK_CONFIG_FIELDS = (
    "max_position_size_usd",
    "max_drawdown_pct",
    "max_daily_loss_usd",
    "max_concurrent_live",
    "portfolio_stop_loss_pct",
    "per_strategy_stop_loss_pct",
    "paper_trading_duration_hours",
    "min_sortino_threshold",
    "max_max_drawdown_pct",
)


async def _get_global_risk_config(session: AsyncSession) -> dict | None:
    result = await session.execute(
        select(RiskConfig).where(
            RiskConfig.label == "global", RiskConfig.is_active.is_(True)
        )
    )
    config = result.scalar_one_or_none()
    if config is None:
        return None
    return {field: getattr(config, field) for field in RISK_CONFIG_FIELDS}


def _merge_risk_config(global_config: dict | None, override: dict | None) -> dict | None:
    if global_config is None and override is None:
        return None
    base = dict(global_config) if global_config else {}
    if override:
        base.update(override)
    return base


async def _build_response(
    experiment: Experiment, session: AsyncSession
) -> ExperimentResponse:
    global_config = await _get_global_risk_config(session)
    effective = _merge_risk_config(global_config, experiment.risk_config_override)
    resp = ExperimentResponse.model_validate(experiment)
    resp.effective_risk_config = effective
    return resp


@router.post("", status_code=201, response_model=ExperimentResponse)
async def create_experiment(
    body: ExperimentCreate, session: AsyncSession = Depends(get_session)
) -> ExperimentResponse:
    experiment = Experiment(**body.model_dump())
    session.add(experiment)
    await session.commit()
    await session.refresh(experiment)
    return await _build_response(experiment, session)


@router.get("", response_model=list[ExperimentResponse])
async def list_experiments(
    include_deleted: bool = Query(False),
    session: AsyncSession = Depends(get_session),
) -> list[ExperimentResponse]:
    stmt = select(Experiment)
    if not include_deleted:
        stmt = stmt.where(Experiment.deleted_at.is_(None))
    stmt = stmt.order_by(Experiment.created_at.desc())
    result = await session.execute(stmt)
    experiments = result.scalars().all()
    return [await _build_response(exp, session) for exp in experiments]


@router.get("/{experiment_id}", response_model=ExperimentResponse)
async def get_experiment(
    experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> ExperimentResponse:
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None or experiment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    return await _build_response(experiment, session)


@router.patch("/{experiment_id}", response_model=ExperimentResponse)
async def update_experiment(
    experiment_id: uuid.UUID,
    body: ExperimentUpdate,
    session: AsyncSession = Depends(get_session),
) -> ExperimentResponse:
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None or experiment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(experiment, field, value)
    await session.commit()
    await session.refresh(experiment)
    return await _build_response(experiment, session)


@router.delete("/{experiment_id}", status_code=204)
async def delete_experiment(
    experiment_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    experiment = await session.get(Experiment, experiment_id)
    if experiment is None or experiment.deleted_at is not None:
        raise HTTPException(status_code=404, detail="Experiment not found")
    now = datetime.now(timezone.utc)
    experiment.deleted_at = now
    result = await session.execute(
        select(StrategyVariation).where(
            StrategyVariation.experiment_id == experiment_id,
            StrategyVariation.deleted_at.is_(None),
        )
    )
    for variation in result.scalars().all():
        variation.deleted_at = now
    await session.commit()
