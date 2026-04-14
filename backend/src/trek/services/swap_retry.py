from __future__ import annotations

import asyncio
import enum
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Protocol

log = logging.getLogger(__name__)

BACKOFF_SCHEDULE = [0.5, 1.0, 2.0, 4.0]
MAX_ATTEMPTS = len(BACKOFF_SCHEDULE) + 1


class SwapError(Exception):
    pass


class RetryableSwapError(SwapError):
    """Stale quote, price moved, quote expired — safe to retry with a fresh quote."""


class AmbiguousSwapError(SwapError):
    """Transaction may have been submitted. NEVER retry — halt immediately."""


class PermanentSwapError(SwapError):
    """Insufficient balance, invalid token, auth failure — no retry."""


class OnMaxRetries(str, enum.Enum):
    SKIP = "skip"
    HALT = "halt"


@dataclass(frozen=True)
class SwapQuote:
    input_mint: str
    output_mint: str
    amount_in: int
    expected_amount_out: int
    slippage_bps: int
    route_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SwapResult:
    tx_signature: str
    amount_in: int
    amount_out: int
    fee: int
    slippage_bps: float


@dataclass(frozen=True)
class SwapFailure:
    error: str
    attempts: int
    halted: bool
    last_exception: Exception | None = None


class QuoteProvider(Protocol):
    async def fetch_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int,
    ) -> SwapQuote: ...


class SwapExecutor(Protocol):
    async def execute_swap(self, quote: SwapQuote) -> SwapResult: ...


async def execute_with_retry(
    quote_provider: QuoteProvider,
    swap_executor: SwapExecutor,
    input_mint: str,
    output_mint: str,
    amount: int,
    slippage_bps: int,
    *,
    on_max_retries: OnMaxRetries = OnMaxRetries.HALT,
    trade_id: uuid.UUID | None = None,
) -> SwapResult | SwapFailure:
    label = str(trade_id) if trade_id else "unknown"

    for attempt in range(MAX_ATTEMPTS):
        try:
            quote = await quote_provider.fetch_quote(
                input_mint, output_mint, amount, slippage_bps,
            )
            log.info(
                "swap attempt %d/%d trade=%s expected_out=%d",
                attempt + 1, MAX_ATTEMPTS, label, quote.expected_amount_out,
            )
            result = await swap_executor.execute_swap(quote)
            log.info(
                "swap succeeded trade=%s tx=%s amount_out=%d",
                label, result.tx_signature, result.amount_out,
            )
            return result

        except AmbiguousSwapError as exc:
            log.error(
                "swap AMBIGUOUS trade=%s attempt=%d — halting immediately: %s",
                label, attempt + 1, exc,
            )
            return SwapFailure(
                error=f"ambiguous state: {exc}",
                attempts=attempt + 1,
                halted=True,
                last_exception=exc,
            )

        except PermanentSwapError as exc:
            log.error(
                "swap permanent failure trade=%s attempt=%d: %s",
                label, attempt + 1, exc,
            )
            halted = on_max_retries == OnMaxRetries.HALT
            return SwapFailure(
                error=f"permanent: {exc}",
                attempts=attempt + 1,
                halted=halted,
                last_exception=exc,
            )

        except RetryableSwapError as exc:
            if attempt < MAX_ATTEMPTS - 1:
                delay = BACKOFF_SCHEDULE[attempt]
                log.warning(
                    "swap retryable failure trade=%s attempt=%d/%d, "
                    "retrying in %.1fs: %s",
                    label, attempt + 1, MAX_ATTEMPTS, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                log.error(
                    "swap exhausted retries trade=%s after %d attempts: %s",
                    label, MAX_ATTEMPTS, exc,
                )
                halted = on_max_retries == OnMaxRetries.HALT
                return SwapFailure(
                    error=f"max retries exhausted: {exc}",
                    attempts=MAX_ATTEMPTS,
                    halted=halted,
                    last_exception=exc,
                )

        except Exception as exc:
            log.error(
                "swap unexpected error trade=%s attempt=%d — treating as ambiguous: %s",
                label, attempt + 1, exc,
            )
            return SwapFailure(
                error=f"unexpected: {exc}",
                attempts=attempt + 1,
                halted=True,
                last_exception=exc,
            )

    # unreachable, but satisfy type checker
    return SwapFailure(error="unreachable", attempts=MAX_ATTEMPTS, halted=True)
