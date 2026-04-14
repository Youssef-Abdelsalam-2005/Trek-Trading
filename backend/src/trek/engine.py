from __future__ import annotations

import asyncio
import logging
import os
import signal

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from trek.jupiter_client import JupiterQuoteClient
from trek.metrics import max_drawdown, sortino_ratio
from trek.models import PaperSession, StrategyStatus, TradeDirection
from trek.orm import PaperSessionRow
from trek.paper_session_store import (
    finalize_session,
    load_active_sessions,
    save_trade,
    update_session_state,
)
from trek.paper_trading import PaperTradingSessionManager, SignalGenerator

logging.basicConfig(level=logging.INFO, format="%(asctime)s [engine] %(message)s")
log = logging.getLogger(__name__)

DECISION_INTERVAL_SECONDS = int(os.environ.get("TREK_DECISION_INTERVAL", "60"))


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        url = os.environ.get("TREK_DATABASE_URL", "postgresql+asyncpg://trek:trek_dev@db:5432/trek")
    return url


class _PlaceholderSignal:
    def generate_signal(self, step: int) -> TradeDirection | None:
        return None


class _PlaceholderQuoteClient:
    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: float,
        slippage_bps: int = 50,
    ):
        from trek.models import QuoteResponse
        return QuoteResponse(
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount=amount,
            out_amount=amount,
            price_impact_pct=0.0,
            route_plan=[],
        )


async def _process_session(
    db: AsyncSession,
    session_row: PaperSessionRow,
    signal_generator: SignalGenerator | None = None,
    quote_client: JupiterQuoteClient | None = None,
) -> None:
    if session_row.current_step >= session_row.total_steps:
        curve = list(session_row.equity_curve)
        if len(curve) < 2:
            status = StrategyStatus.PAPER_FAILED
            s, dd = 0.0, 0.0
        else:
            returns = [
                (curve[i] - curve[i - 1]) / curve[i - 1]
                for i in range(1, len(curve))
                if curve[i - 1] > 0
            ]
            s = sortino_ratio(returns)
            dd = max_drawdown(curve)
            passed = s >= session_row.sortino_threshold and dd <= session_row.max_drawdown_threshold
            status = StrategyStatus.PAPER_PASSED if passed else StrategyStatus.PAPER_FAILED

        await finalize_session(db, session_row, status=status, sortino=s, max_dd=dd)
        log.info(
            "Session %s finalized: %s (sortino=%.4f, max_dd=%.4f)",
            session_row.id, status.value, s, dd,
        )
        return

    domain_session = PaperSession(
        id=session_row.id,
        variation_id=session_row.variation_id,
        status=StrategyStatus(session_row.status),
        start_time=session_row.start_time,
        duration_days=session_row.duration_days,
        drop_rate=session_row.drop_rate,
        sortino_threshold=session_row.sortino_threshold,
        max_drawdown_threshold=session_row.max_drawdown_threshold,
        initial_capital=session_row.initial_capital,
        equity_curve=list(session_row.equity_curve),
    )

    sig_gen = signal_generator or _PlaceholderSignal()
    qc = quote_client or _PlaceholderQuoteClient()

    manager = PaperTradingSessionManager(
        session=domain_session,
        signal_generator=sig_gen,
        quote_client=qc,
    )
    manager.restore_state(
        capital=session_row.current_capital,
        position=session_row.current_position,
    )

    step = session_row.current_step
    result = await manager.execute_step(step, session_row.total_steps)

    if result.trade is not None:
        await save_trade(db, session_row, result.trade, step)

    await update_session_state(
        db,
        session_row,
        capital=result.capital,
        position=result.position,
        equity_value=result.equity_value,
        step=step + 1,
    )

    if result.finished and result.final_status is not None:
        await finalize_session(
            db,
            session_row,
            status=result.final_status,
            sortino=result.sortino,
            max_dd=result.max_dd,
        )
        log.info(
            "Session %s completed: %s (sortino=%.4f, max_dd=%.4f)",
            session_row.id, result.final_status.value, result.sortino, result.max_dd,
        )
    else:
        log.info(
            "Session %s step %d/%d equity=%.2f",
            session_row.id, step + 1, session_row.total_steps, result.equity_value,
        )


async def run_tick(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as db:
        sessions = await load_active_sessions(db)
        if not sessions:
            return 0

        for session_row in sessions:
            try:
                await _process_session(db, session_row)
            except Exception:
                log.exception("Error processing session %s", session_row.id)
                continue

        await db.commit()
        return len(sessions)


async def main() -> None:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)

    db_url = _database_url()
    engine = create_async_engine(db_url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    log.info("Execution engine started — monitoring loop active (interval=%ds)", DECISION_INTERVAL_SECONDS)

    try:
        while not stop.is_set():
            try:
                processed = await run_tick(session_factory)
                if processed:
                    log.info("Processed %d active session(s)", processed)
            except Exception:
                log.exception("Error in engine tick")

            try:
                await asyncio.wait_for(stop.wait(), timeout=DECISION_INTERVAL_SECONDS)
            except asyncio.TimeoutError:
                pass
    finally:
        await engine.dispose()
        log.info("Execution engine shutting down")


if __name__ == "__main__":
    asyncio.run(main())
