from __future__ import annotations

import json

import httpx
import pytest

from trek.services.jupiter import (
    DEFAULT_BASE_URL,
    SOL_MINT,
    USDC_MINT,
    JupiterAPIError,
    JupiterQuoteClient,
)

SAMPLE_QUOTE_RESPONSE = {
    "inputMint": SOL_MINT,
    "inAmount": "1000000000",
    "outputMint": USDC_MINT,
    "outAmount": "150000000",
    "otherAmountThreshold": "149250000",
    "swapMode": "ExactIn",
    "slippageBps": 50,
    "priceImpactPct": "0.01",
    "routePlan": [
        {
            "swapInfo": {
                "ammKey": "amm123",
                "label": "Raydium",
                "inputMint": SOL_MINT,
                "outputMint": USDC_MINT,
                "inAmount": "1000000000",
                "outAmount": "150000000",
            },
            "percent": 100,
        }
    ],
    "contextSlot": 12345678,
    "timeTaken": 0.05,
}


def _mock_transport(responses: list[httpx.Response]) -> httpx.MockTransport:
    call_count = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal call_count
        idx = min(call_count, len(responses) - 1)
        call_count += 1
        return responses[idx]

    return httpx.MockTransport(handler)


@pytest.fixture
def sample_response() -> httpx.Response:
    return httpx.Response(200, json=SAMPLE_QUOTE_RESPONSE)


async def test_get_quote_success(sample_response: httpx.Response) -> None:
    transport = _mock_transport([sample_response])
    async with JupiterQuoteClient(
        base_url="https://test.local", base_backoff_seconds=0.01
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport, base_url="https://test.local"
        )
        quote = await client.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)

    assert quote.input_mint == SOL_MINT
    assert quote.output_mint == USDC_MINT
    assert quote.out_amount == "150000000"
    assert quote.price_impact_pct == "0.01"
    assert quote.slippage_bps == 50
    assert len(quote.route_plan) == 1
    assert quote.route_plan[0].swap_info.label == "Raydium"
    assert quote.route_plan[0].percent == 100


async def test_retry_on_429(sample_response: httpx.Response) -> None:
    rate_limited = httpx.Response(429, text="Too Many Requests")
    transport = _mock_transport([rate_limited, rate_limited, sample_response])

    async with JupiterQuoteClient(
        base_url="https://test.local", base_backoff_seconds=0.01
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport, base_url="https://test.local"
        )
        quote = await client.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)

    assert quote.out_amount == "150000000"


async def test_retry_on_429_respects_retry_after(
    sample_response: httpx.Response,
) -> None:
    rate_limited = httpx.Response(
        429, text="Too Many Requests", headers={"Retry-After": "0.01"}
    )
    transport = _mock_transport([rate_limited, sample_response])

    async with JupiterQuoteClient(
        base_url="https://test.local", base_backoff_seconds=0.01
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport, base_url="https://test.local"
        )
        quote = await client.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)

    assert quote.out_amount == "150000000"


async def test_retry_on_500(sample_response: httpx.Response) -> None:
    server_error = httpx.Response(500, text="Internal Server Error")
    transport = _mock_transport([server_error, sample_response])

    async with JupiterQuoteClient(
        base_url="https://test.local", base_backoff_seconds=0.01
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport, base_url="https://test.local"
        )
        quote = await client.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)

    assert quote.out_amount == "150000000"


async def test_raises_on_4xx() -> None:
    bad_request = httpx.Response(400, text="Bad Request")
    transport = _mock_transport([bad_request])

    async with JupiterQuoteClient(
        base_url="https://test.local", base_backoff_seconds=0.01
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport, base_url="https://test.local"
        )
        with pytest.raises(JupiterAPIError) as exc_info:
            await client.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)

    assert exc_info.value.status_code == 400


async def test_exhausted_retries_raises() -> None:
    server_error = httpx.Response(500, text="Internal Server Error")
    transport = _mock_transport([server_error] * 10)

    async with JupiterQuoteClient(
        base_url="https://test.local", max_retries=2, base_backoff_seconds=0.01
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport, base_url="https://test.local"
        )
        with pytest.raises(JupiterAPIError) as exc_info:
            await client.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)

    assert exc_info.value.status_code == 500


async def test_multi_hop_route() -> None:
    data = {
        **SAMPLE_QUOTE_RESPONSE,
        "routePlan": [
            {
                "swapInfo": {
                    "ammKey": "amm1",
                    "label": "Raydium",
                    "inputMint": SOL_MINT,
                    "outputMint": "intermediate_mint",
                    "inAmount": "1000000000",
                    "outAmount": "500000",
                },
                "percent": 100,
            },
            {
                "swapInfo": {
                    "ammKey": "amm2",
                    "label": "Orca",
                    "inputMint": "intermediate_mint",
                    "outputMint": USDC_MINT,
                    "inAmount": "500000",
                    "outAmount": "150000000",
                },
                "percent": 100,
            },
        ],
    }
    transport = _mock_transport([httpx.Response(200, json=data)])

    async with JupiterQuoteClient(
        base_url="https://test.local", base_backoff_seconds=0.01
    ) as client:
        client._client = httpx.AsyncClient(
            transport=transport, base_url="https://test.local"
        )
        quote = await client.get_quote(SOL_MINT, USDC_MINT, 1_000_000_000)

    assert len(quote.route_plan) == 2
    assert quote.route_plan[0].swap_info.label == "Raydium"
    assert quote.route_plan[1].swap_info.label == "Orca"


@pytest.mark.integration
async def test_live_sol_usdc_quote() -> None:
    async with JupiterQuoteClient() as client:
        quote = await client.get_quote(
            input_mint=SOL_MINT,
            output_mint=USDC_MINT,
            amount=1_000_000_000,
            slippage_bps=50,
        )

    assert quote.input_mint == SOL_MINT
    assert quote.output_mint == USDC_MINT
    assert int(quote.in_amount) == 1_000_000_000
    assert int(quote.out_amount) > 0
    assert len(quote.route_plan) >= 1
    assert quote.price_impact_pct is not None
    assert quote.other_amount_threshold is not None
