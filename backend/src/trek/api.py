from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import Depends, FastAPI
from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.models.enums import StrategyStatus
from backend.app.schemas.kill_switch_event import (
    KillSwitchEventCreate,
    KillSwitchEventResponse,
)
from trek.db import get_session
from trek.routers.trades import router as trades_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s [api] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Trek Trading API")
app.include_router(trades_router)

KILL_SWITCH_CHANNEL = "kill_switch"


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/api/kill-switch", response_model=KillSwitchEventResponse)
async def kill_switch(
    body: KillSwitchEventCreate,
    session: AsyncSession = Depends(get_session),
) -> KillSwitchEventResponse:
    target_statuses = [s.value for s in StrategyStatus.kill_switch_states()]

    async with session.begin():
        stmt = text("""
            UPDATE strategy_variation
            SET status = :killed, updated_at = now()
            WHERE status IN :targets
            RETURNING id
        """).bindparams(bindparam("targets", expanding=True))

        result = await session.execute(
            stmt,
            {"killed": StrategyStatus.KILLED.value, "targets": target_statuses},
        )
        killed_ids = [row[0] for row in result.fetchall()]
        count = len(killed_ids)

        event_id = uuid.uuid4()
        now = datetime.now(timezone.utc)
        await session.execute(
            text("""
                INSERT INTO kill_switch_event
                    (id, reason, triggered_by, strategies_affected, details, created_at, updated_at)
                VALUES
                    (:id, :reason, :triggered_by, :count, :details, :now, :now)
            """),
            {
                "id": event_id,
                "reason": body.reason,
                "triggered_by": body.triggered_by,
                "count": count,
                "details": json.dumps({"killed_ids": [str(i) for i in killed_ids]}),
                "now": now,
            },
        )

        await session.execute(
            text("SELECT pg_notify(:channel, :payload)"),
            {"channel": KILL_SWITCH_CHANNEL, "payload": str(event_id)},
        )

    log.info(
        "kill_switch activated: %d strategies killed, event=%s",
        count, event_id,
    )

    return KillSwitchEventResponse(
        id=event_id,
        created_at=now,
        updated_at=now,
        reason=body.reason,
        triggered_by=body.triggered_by,
        strategies_affected=count,
        details={"killed_ids": [str(i) for i in killed_ids]},
    )
