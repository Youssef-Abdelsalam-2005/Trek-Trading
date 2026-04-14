from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from trek.models import (
    PaperSession,
    PaperTrade,
    StrategyStatus,
    TradeDirection,
)
from trek.orm import PaperSessionRow, PaperTradeRow


async def create_session(db: AsyncSession, session: PaperSession, total_steps: int) -> PaperSessionRow:
    row = PaperSessionRow(
        id=session.id,
        variation_id=session.variation_id,
        status=session.status.value,
        start_time=session.start_time,
        duration_days=session.duration_days,
        drop_rate=session.drop_rate,
        sortino_threshold=session.sortino_threshold,
        max_drawdown_threshold=session.max_drawdown_threshold,
        initial_capital=session.initial_capital,
        current_capital=session.initial_capital,
        current_position=0.0,
        equity_curve=[session.initial_capital],
        current_step=0,
        total_steps=total_steps,
    )
    db.add(row)
    await db.flush()
    return row


async def load_session(db: AsyncSession, session_id: uuid.UUID) -> PaperSessionRow | None:
    result = await db.execute(
        select(PaperSessionRow).where(PaperSessionRow.id == session_id)
    )
    return result.scalar_one_or_none()


async def load_active_sessions(db: AsyncSession) -> list[PaperSessionRow]:
    result = await db.execute(
        select(PaperSessionRow).where(
            PaperSessionRow.status == StrategyStatus.PAPER_TRADING.value
        )
    )
    return list(result.scalars().all())


async def save_trade(db: AsyncSession, session_row: PaperSessionRow, trade: PaperTrade, step: int) -> PaperTradeRow:
    row = PaperTradeRow(
        id=trade.id,
        session_id=session_row.id,
        timestamp=trade.timestamp,
        step=step,
        direction=trade.direction.value,
        input_mint=trade.input_mint,
        output_mint=trade.output_mint,
        in_amount=trade.in_amount,
        quoted_out_amount=trade.quoted_out_amount,
        filled=trade.filled,
        price_impact_pct=trade.price_impact_pct,
    )
    db.add(row)
    return row


async def update_session_state(
    db: AsyncSession,
    session_row: PaperSessionRow,
    *,
    capital: float,
    position: float,
    equity_value: float,
    step: int,
) -> None:
    equity_curve = list(session_row.equity_curve)
    equity_curve.append(equity_value)
    session_row.equity_curve = equity_curve
    session_row.current_capital = capital
    session_row.current_position = position
    session_row.current_step = step
    session_row.updated_at = datetime.now(timezone.utc)


async def finalize_session(
    db: AsyncSession,
    session_row: PaperSessionRow,
    *,
    status: StrategyStatus,
    sortino: float,
    max_dd: float,
) -> None:
    session_row.status = status.value
    session_row.sortino_result = sortino
    session_row.max_drawdown_result = max_dd
    session_row.end_time = datetime.now(timezone.utc)
    session_row.updated_at = datetime.now(timezone.utc)


def row_to_domain(row: PaperSessionRow) -> PaperSession:
    return PaperSession(
        id=row.id,
        variation_id=row.variation_id,
        status=StrategyStatus(row.status),
        start_time=row.start_time,
        duration_days=row.duration_days,
        drop_rate=row.drop_rate,
        sortino_threshold=row.sortino_threshold,
        max_drawdown_threshold=row.max_drawdown_threshold,
        initial_capital=row.initial_capital,
        equity_curve=list(row.equity_curve),
    )
