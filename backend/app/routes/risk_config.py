import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models.risk_config import RiskConfig
from backend.app.schemas.risk_config import (
    RiskConfigCreate,
    RiskConfigOverrideCreate,
    RiskConfigResolved,
    RiskConfigResponse,
    RiskConfigUpdate,
)

router = APIRouter(prefix="/api/risk-config", tags=["risk-config"])


async def _get_or_create_global(db: AsyncSession) -> RiskConfig:
    stmt = select(RiskConfig).where(RiskConfig.experiment_id.is_(None))
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is not None:
        return row
    row = RiskConfig(**RiskConfig.GLOBAL_DEFAULTS)
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


def _resolve(global_row: RiskConfig, override_row: RiskConfig | None) -> dict:
    resolved = {}
    for field in RiskConfig.RISK_FIELDS:
        override_val = getattr(override_row, field, None) if override_row else None
        if override_val is not None:
            resolved[field] = override_val
        else:
            resolved[field] = getattr(global_row, field)
    return resolved


@router.get("/global", response_model=RiskConfigResponse)
async def get_global_config(db: AsyncSession = Depends(get_db)):
    row = await _get_or_create_global(db)
    return row


@router.put("/global", response_model=RiskConfigResponse)
async def update_global_config(
    body: RiskConfigCreate, db: AsyncSession = Depends(get_db)
):
    row = await _get_or_create_global(db)
    for field in RiskConfig.RISK_FIELDS:
        setattr(row, field, getattr(body, field))
    await db.commit()
    await db.refresh(row)
    return row


@router.patch("/global", response_model=RiskConfigResponse)
async def patch_global_config(
    body: RiskConfigUpdate, db: AsyncSession = Depends(get_db)
):
    row = await _get_or_create_global(db)
    updates = body.model_dump(exclude_unset=True)
    for field, value in updates.items():
        setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.get(
    "/experiments/{experiment_id}", response_model=RiskConfigResponse
)
async def get_experiment_override(
    experiment_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    stmt = select(RiskConfig).where(RiskConfig.experiment_id == experiment_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "No override for this experiment")
    return row


@router.put(
    "/experiments/{experiment_id}", response_model=RiskConfigResponse
)
async def upsert_experiment_override(
    experiment_id: uuid.UUID,
    body: RiskConfigUpdate,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(RiskConfig).where(RiskConfig.experiment_id == experiment_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    updates = body.model_dump(exclude_unset=True)
    if row is None:
        row = RiskConfig(experiment_id=experiment_id, **updates)
        db.add(row)
    else:
        for field, value in updates.items():
            setattr(row, field, value)
    await db.commit()
    await db.refresh(row)
    return row


@router.delete(
    "/experiments/{experiment_id}", status_code=204
)
async def delete_experiment_override(
    experiment_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    stmt = select(RiskConfig).where(RiskConfig.experiment_id == experiment_id)
    result = await db.execute(stmt)
    row = result.scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "No override for this experiment")
    await db.delete(row)
    await db.commit()


@router.get(
    "/experiments/{experiment_id}/resolved",
    response_model=RiskConfigResolved,
)
async def get_resolved_config(
    experiment_id: uuid.UUID, db: AsyncSession = Depends(get_db)
):
    global_row = await _get_or_create_global(db)
    stmt = select(RiskConfig).where(RiskConfig.experiment_id == experiment_id)
    result = await db.execute(stmt)
    override_row = result.scalar_one_or_none()
    resolved = _resolve(global_row, override_row)
    resolved["experiment_id"] = experiment_id
    return resolved
