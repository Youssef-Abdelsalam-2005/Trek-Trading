from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from trek.engine import _process_session
from trek.models import (
    PaperSession,
    PaperTrade,
    QuoteResponse,
    StrategyStatus,
    TradeDirection,
)
from trek.orm import Base, PaperSessionRow, PaperTradeRow
from trek.paper_session_store import create_session, load_session
from trek.paper_trading import SignalGenerator


class AlwaysBuySignal:
    def generate_signal(self, step: int) -> TradeDirection | None:
        return TradeDirection.BUY


class FakeQuoteClient:
    async def get_quote(self, input_mint, output_mint, amount, slippage_bps=50):
        return QuoteResponse(
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount=amount,
            out_amount=amount * 1.02,
            price_impact_pct=0.1,
            route_plan=[{"swap": "direct"}],
        )


def _make_session(**kwargs) -> PaperSession:
    defaults = {
        "initial_capital": 1000.0,
        "drop_rate": 0.0,
        "sortino_threshold": 0.0,
        "max_drawdown_threshold": 0.99,
    }
    defaults.update(kwargs)
    return PaperSession(**defaults)


class TestEngineProcessSession:
    @pytest.mark.asyncio
    async def test_single_step(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=5)
        await db_session.commit()

        await _process_session(
            db_session, row,
            signal_generator=AlwaysBuySignal(),
            quote_client=FakeQuoteClient(),
        )
        await db_session.commit()

        loaded = await load_session(db_session, session.id)
        assert loaded is not None
        assert loaded.current_step == 1
        assert loaded.status == "paper_trading"
        assert len(loaded.equity_curve) == 2

    @pytest.mark.asyncio
    async def test_full_session_completes(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=3)
        await db_session.commit()

        for _ in range(3):
            row = await load_session(db_session, session.id)
            await _process_session(
                db_session, row,
                signal_generator=AlwaysBuySignal(),
                quote_client=FakeQuoteClient(),
            )
            await db_session.commit()

        loaded = await load_session(db_session, session.id)
        assert loaded is not None
        assert loaded.status in ("paper_passed", "paper_failed")
        assert loaded.end_time is not None
        assert loaded.sortino_result is not None
        assert loaded.max_drawdown_result is not None

    @pytest.mark.asyncio
    async def test_trades_persisted_per_step(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=3)
        await db_session.commit()

        for _ in range(3):
            row = await load_session(db_session, session.id)
            await _process_session(
                db_session, row,
                signal_generator=AlwaysBuySignal(),
                quote_client=FakeQuoteClient(),
            )
            await db_session.commit()

        result = await db_session.execute(
            select(PaperTradeRow).where(PaperTradeRow.session_id == session.id)
        )
        trades = list(result.scalars().all())
        assert len(trades) == 3

    @pytest.mark.asyncio
    async def test_session_already_at_total_steps_finalizes(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=0)
        await db_session.commit()

        await _process_session(db_session, row)
        await db_session.commit()

        loaded = await load_session(db_session, session.id)
        assert loaded is not None
        assert loaded.status == "paper_failed"
