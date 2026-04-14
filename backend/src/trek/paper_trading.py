from __future__ import annotations

import random
from collections.abc import Callable
from typing import Protocol

from trek.jupiter_client import JupiterQuoteClient
from trek.metrics import max_drawdown, sortino_ratio
from trek.models import (
    PaperSession,
    PaperTrade,
    QuoteResponse,
    StrategyStatus,
    TradeDirection,
)


class SignalGenerator(Protocol):
    def generate_signal(self, step: int) -> TradeDirection | None: ...


class PaperTradingSessionManager:
    def __init__(
        self,
        session: PaperSession,
        signal_generator: SignalGenerator,
        quote_client: JupiterQuoteClient,
        rng: random.Random | None = None,
    ) -> None:
        self.session = session
        self.signal_generator = signal_generator
        self.quote_client = quote_client
        self.rng = rng or random.Random()
        self._capital = session.initial_capital
        self._position: float = 0.0

    async def run(self, num_steps: int) -> PaperSession:
        self.session.equity_curve = [self._capital]

        for step in range(num_steps):
            signal = self.signal_generator.generate_signal(step)
            if signal is None:
                self.session.equity_curve.append(self._capital + self._position)
                continue

            await self._execute_signal(signal, step)
            self.session.equity_curve.append(self._capital + self._position)

        self._evaluate_session()
        return self.session

    async def _execute_signal(self, direction: TradeDirection, step: int) -> None:
        if direction == TradeDirection.BUY:
            input_mint = "So11111111111111111111111111111111111111112"
            output_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            amount = self._capital * 0.1
        else:
            input_mint = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
            output_mint = "So11111111111111111111111111111111111111112"
            amount = self._position * 0.5 if self._position > 0 else 0

        if amount <= 0:
            return

        quote = await self.quote_client.get_quote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount=amount,
        )

        filled = self.rng.random() >= self.session.drop_rate

        trade = PaperTrade(
            session_id=self.session.id,
            direction=direction,
            input_mint=input_mint,
            output_mint=output_mint,
            in_amount=amount,
            quoted_out_amount=quote.out_amount,
            filled=filled,
            price_impact_pct=quote.price_impact_pct,
        )
        self.session.trades.append(trade)

        if filled:
            if direction == TradeDirection.BUY:
                self._capital -= amount
                self._position += quote.out_amount
            else:
                self._position -= amount
                self._capital += quote.out_amount

    def _evaluate_session(self) -> None:
        curve = self.session.equity_curve
        if len(curve) < 2:
            self.session.status = StrategyStatus.PAPER_FAILED
            return

        returns = [
            (curve[i] - curve[i - 1]) / curve[i - 1]
            for i in range(1, len(curve))
            if curve[i - 1] > 0
        ]

        session_sortino = sortino_ratio(returns)
        session_max_dd = max_drawdown(curve)

        passed = (
            session_sortino >= self.session.sortino_threshold
            and session_max_dd <= self.session.max_drawdown_threshold
        )
        self.session.status = (
            StrategyStatus.PAPER_PASSED if passed else StrategyStatus.PAPER_FAILED
        )
