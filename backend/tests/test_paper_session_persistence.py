from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from trek.models import PaperSession, PaperTrade, StrategyStatus, TradeDirection
from trek.orm import PaperSessionRow, PaperTradeRow
from trek.paper_session_store import (
    create_session,
    finalize_session,
    load_active_sessions,
    load_session,
    row_to_domain,
    save_trade,
    update_session_state,
)


def _make_session(**kwargs) -> PaperSession:
    defaults = {
        "initial_capital": 1000.0,
        "drop_rate": 0.0,
        "sortino_threshold": 0.5,
        "max_drawdown_threshold": 0.30,
    }
    defaults.update(kwargs)
    return PaperSession(**defaults)


class TestCreateAndLoadSession:
    @pytest.mark.asyncio
    async def test_round_trip(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=168)
        await db_session.commit()

        loaded = await load_session(db_session, session.id)
        assert loaded is not None
        assert loaded.id == session.id
        assert loaded.variation_id == session.variation_id
        assert loaded.status == "paper_trading"
        assert loaded.initial_capital == 1000.0
        assert loaded.total_steps == 168
        assert loaded.current_step == 0
        assert loaded.equity_curve == [1000.0]

    @pytest.mark.asyncio
    async def test_load_nonexistent(self, db_session: AsyncSession) -> None:
        loaded = await load_session(db_session, uuid.uuid4())
        assert loaded is None


class TestLoadActiveSessions:
    @pytest.mark.asyncio
    async def test_returns_only_active(self, db_session: AsyncSession) -> None:
        s1 = _make_session()
        s2 = _make_session()
        await create_session(db_session, s1, total_steps=10)
        row2 = await create_session(db_session, s2, total_steps=10)
        row2.status = "paper_passed"
        await db_session.commit()

        active = await load_active_sessions(db_session)
        assert len(active) == 1
        assert active[0].id == s1.id


class TestSaveTrade:
    @pytest.mark.asyncio
    async def test_trade_persisted(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=10)

        trade = PaperTrade(
            session_id=session.id,
            direction=TradeDirection.BUY,
            input_mint="So11111111111111111111111111111111111111112",
            output_mint="EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
            in_amount=100.0,
            quoted_out_amount=102.0,
            filled=True,
            price_impact_pct=0.05,
        )
        await save_trade(db_session, row, trade, step=0)
        await db_session.commit()

        result = await db_session.execute(
            select(PaperTradeRow).where(PaperTradeRow.session_id == session.id)
        )
        trades = list(result.scalars().all())
        assert len(trades) == 1
        assert trades[0].direction == "buy"
        assert trades[0].in_amount == 100.0
        assert trades[0].filled is True


class TestUpdateSessionState:
    @pytest.mark.asyncio
    async def test_state_updated(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=10)

        await update_session_state(
            db_session, row,
            capital=900.0, position=102.0, equity_value=1002.0, step=1,
        )
        await db_session.commit()

        loaded = await load_session(db_session, session.id)
        assert loaded is not None
        assert loaded.current_capital == 900.0
        assert loaded.current_position == 102.0
        assert loaded.current_step == 1
        assert loaded.equity_curve == [1000.0, 1002.0]


class TestFinalizeSession:
    @pytest.mark.asyncio
    async def test_finalize_passed(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=10)

        await finalize_session(
            db_session, row,
            status=StrategyStatus.PAPER_PASSED,
            sortino=1.5,
            max_dd=0.10,
        )
        await db_session.commit()

        loaded = await load_session(db_session, session.id)
        assert loaded is not None
        assert loaded.status == "paper_passed"
        assert loaded.sortino_result == 1.5
        assert loaded.max_drawdown_result == 0.10
        assert loaded.end_time is not None

    @pytest.mark.asyncio
    async def test_finalize_failed(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=10)

        await finalize_session(
            db_session, row,
            status=StrategyStatus.PAPER_FAILED,
            sortino=0.2,
            max_dd=0.50,
        )
        await db_session.commit()

        loaded = await load_session(db_session, session.id)
        assert loaded is not None
        assert loaded.status == "paper_failed"


class TestRowToDomain:
    @pytest.mark.asyncio
    async def test_conversion(self, db_session: AsyncSession) -> None:
        session = _make_session(initial_capital=5000.0)
        row = await create_session(db_session, session, total_steps=100)
        await db_session.commit()

        domain = row_to_domain(row)
        assert domain.id == session.id
        assert domain.initial_capital == 5000.0
        assert domain.status == StrategyStatus.PAPER_TRADING
        assert domain.equity_curve == [5000.0]


class TestRestartRecovery:
    @pytest.mark.asyncio
    async def test_session_survives_simulated_restart(self, db_session: AsyncSession) -> None:
        session = _make_session()
        row = await create_session(db_session, session, total_steps=10)

        for step_i in range(5):
            await update_session_state(
                db_session, row,
                capital=1000.0 - step_i * 10,
                position=step_i * 10.2,
                equity_value=1000.0 + step_i * 0.2,
                step=step_i + 1,
            )
        await db_session.commit()

        reloaded = await load_session(db_session, session.id)
        assert reloaded is not None
        assert reloaded.current_step == 5
        assert reloaded.current_capital == 960.0
        assert reloaded.current_position == 40.8
        assert len(reloaded.equity_curve) == 6
        assert reloaded.status == "paper_trading"
