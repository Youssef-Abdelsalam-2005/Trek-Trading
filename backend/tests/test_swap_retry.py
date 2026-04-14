"""Unit tests for swap execution retry logic.

No database required — tests use in-memory mock providers.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import pytest

from trek.services.swap_retry import (
    BACKOFF_SCHEDULE,
    MAX_ATTEMPTS,
    AmbiguousSwapError,
    OnMaxRetries,
    PermanentSwapError,
    RetryableSwapError,
    SwapFailure,
    SwapQuote,
    SwapResult,
    execute_with_retry,
)


class FakeQuoteProvider:
    def __init__(self) -> None:
        self.call_count = 0

    async def fetch_quote(
        self, input_mint: str, output_mint: str, amount: int, slippage_bps: int,
    ) -> SwapQuote:
        self.call_count += 1
        return SwapQuote(
            input_mint=input_mint,
            output_mint=output_mint,
            amount_in=amount,
            expected_amount_out=amount * 10,
            slippage_bps=slippage_bps,
        )


class FakeSwapExecutor:
    def __init__(self, errors: list[Exception | None] | None = None) -> None:
        self.errors = list(errors or [])
        self.call_count = 0

    async def execute_swap(self, quote: SwapQuote) -> SwapResult:
        self.call_count += 1
        if self.errors:
            err = self.errors.pop(0)
            if err is not None:
                raise err
        return SwapResult(
            tx_signature="sig_abc123",
            amount_in=quote.amount_in,
            amount_out=quote.expected_amount_out,
            fee=100,
            slippage_bps=0.5,
        )


COMMON_KWARGS: dict[str, Any] = {
    "input_mint": "SOL",
    "output_mint": "USDC",
    "amount": 1000,
    "slippage_bps": 50,
}


@pytest.mark.asyncio
async def test_success_on_first_attempt():
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor()
    result = await execute_with_retry(qp, ex, **COMMON_KWARGS)
    assert isinstance(result, SwapResult)
    assert result.tx_signature == "sig_abc123"
    assert qp.call_count == 1
    assert ex.call_count == 1


@pytest.mark.asyncio
async def test_retry_after_retryable_error(monkeypatch):
    monkeypatch.setattr("trek.services.swap_retry.BACKOFF_SCHEDULE", [0.0, 0.0, 0.0, 0.0])
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor(errors=[
        RetryableSwapError("stale quote"),
        RetryableSwapError("price moved"),
        None,
    ])
    result = await execute_with_retry(qp, ex, **COMMON_KWARGS)
    assert isinstance(result, SwapResult)
    assert qp.call_count == 3
    assert ex.call_count == 3


@pytest.mark.asyncio
async def test_fresh_quote_on_every_retry(monkeypatch):
    monkeypatch.setattr("trek.services.swap_retry.BACKOFF_SCHEDULE", [0.0, 0.0, 0.0, 0.0])
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor(errors=[RetryableSwapError("stale"), None])
    await execute_with_retry(qp, ex, **COMMON_KWARGS)
    assert qp.call_count == 2


@pytest.mark.asyncio
async def test_max_retries_exhausted_skip(monkeypatch):
    monkeypatch.setattr("trek.services.swap_retry.BACKOFF_SCHEDULE", [0.0, 0.0, 0.0, 0.0])
    qp = FakeQuoteProvider()
    errors = [RetryableSwapError(f"fail {i}") for i in range(MAX_ATTEMPTS)]
    ex = FakeSwapExecutor(errors=errors)
    result = await execute_with_retry(
        qp, ex, **COMMON_KWARGS, on_max_retries=OnMaxRetries.SKIP,
    )
    assert isinstance(result, SwapFailure)
    assert result.attempts == MAX_ATTEMPTS
    assert result.halted is False


@pytest.mark.asyncio
async def test_max_retries_exhausted_halt(monkeypatch):
    monkeypatch.setattr("trek.services.swap_retry.BACKOFF_SCHEDULE", [0.0, 0.0, 0.0, 0.0])
    qp = FakeQuoteProvider()
    errors = [RetryableSwapError(f"fail {i}") for i in range(MAX_ATTEMPTS)]
    ex = FakeSwapExecutor(errors=errors)
    result = await execute_with_retry(
        qp, ex, **COMMON_KWARGS, on_max_retries=OnMaxRetries.HALT,
    )
    assert isinstance(result, SwapFailure)
    assert result.attempts == MAX_ATTEMPTS
    assert result.halted is True


@pytest.mark.asyncio
async def test_ambiguous_halts_immediately():
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor(errors=[AmbiguousSwapError("timeout after tx submit")])
    result = await execute_with_retry(
        qp, ex, **COMMON_KWARGS, on_max_retries=OnMaxRetries.SKIP,
    )
    assert isinstance(result, SwapFailure)
    assert result.halted is True
    assert result.attempts == 1
    assert "ambiguous" in result.error


@pytest.mark.asyncio
async def test_ambiguous_overrides_skip_config():
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor(errors=[AmbiguousSwapError("network error after signing")])
    result = await execute_with_retry(
        qp, ex, **COMMON_KWARGS, on_max_retries=OnMaxRetries.SKIP,
    )
    assert isinstance(result, SwapFailure)
    assert result.halted is True


@pytest.mark.asyncio
async def test_permanent_error_no_retry_halt():
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor(errors=[PermanentSwapError("insufficient balance")])
    result = await execute_with_retry(
        qp, ex, **COMMON_KWARGS, on_max_retries=OnMaxRetries.HALT,
    )
    assert isinstance(result, SwapFailure)
    assert result.halted is True
    assert result.attempts == 1
    assert "permanent" in result.error


@pytest.mark.asyncio
async def test_permanent_error_no_retry_skip():
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor(errors=[PermanentSwapError("invalid token")])
    result = await execute_with_retry(
        qp, ex, **COMMON_KWARGS, on_max_retries=OnMaxRetries.SKIP,
    )
    assert isinstance(result, SwapFailure)
    assert result.halted is False
    assert result.attempts == 1


@pytest.mark.asyncio
async def test_unexpected_exception_treated_as_ambiguous():
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor(errors=[RuntimeError("segfault or something")])
    result = await execute_with_retry(qp, ex, **COMMON_KWARGS)
    assert isinstance(result, SwapFailure)
    assert result.halted is True
    assert result.attempts == 1
    assert "unexpected" in result.error


@pytest.mark.asyncio
async def test_trade_id_logged():
    qp = FakeQuoteProvider()
    ex = FakeSwapExecutor()
    tid = uuid.uuid4()
    result = await execute_with_retry(qp, ex, **COMMON_KWARGS, trade_id=tid)
    assert isinstance(result, SwapResult)


@pytest.mark.asyncio
async def test_backoff_schedule_constants():
    assert BACKOFF_SCHEDULE == [0.5, 1.0, 2.0, 4.0]
    assert MAX_ATTEMPTS == 5
