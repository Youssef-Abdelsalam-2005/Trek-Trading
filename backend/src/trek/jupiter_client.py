from __future__ import annotations

from typing import Protocol

from trek.models import QuoteResponse


class JupiterQuoteClient(Protocol):
    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: float,
        slippage_bps: int = 50,
    ) -> QuoteResponse: ...
