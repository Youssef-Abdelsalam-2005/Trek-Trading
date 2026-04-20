from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from backend.app.schemas.jupiter import JupiterQuote

log = logging.getLogger(__name__)

SOL_MINT = "So11111111111111111111111111111111111111112"
USDC_MINT = "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"

DEFAULT_BASE_URL = "https://quote-api.jup.ag/v6"


class JupiterAPIError(Exception):
    def __init__(self, status_code: int, body: str):
        self.status_code = status_code
        self.body = body
        super().__init__(f"Jupiter API error {status_code}: {body}")


class JupiterQuoteClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_BASE_URL,
        timeout_seconds: float = 10.0,
        max_retries: int = 3,
        base_backoff_seconds: float = 1.0,
    ):
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._client = httpx.AsyncClient(
            base_url=self._base_url,
            timeout=httpx.Timeout(timeout_seconds),
        )

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> JupiterQuoteClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def get_quote(
        self,
        input_mint: str,
        output_mint: str,
        amount: int,
        slippage_bps: int = 50,
        *,
        swap_mode: str = "ExactIn",
    ) -> JupiterQuote:
        params: dict[str, Any] = {
            "inputMint": input_mint,
            "outputMint": output_mint,
            "amount": str(amount),
            "slippageBps": slippage_bps,
            "swapMode": swap_mode,
        }

        data = await self._request_with_retry("/quote", params)
        return _parse_quote(data)

    async def _request_with_retry(
        self, path: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.get(path, params=params)

                if resp.status_code == 429:
                    retry_after = resp.headers.get("Retry-After")
                    delay = (
                        float(retry_after)
                        if retry_after
                        else self._base_backoff * (2**attempt)
                    )
                    log.warning(
                        "jupiter rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay,
                        attempt + 1,
                        self._max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code >= 500:
                    delay = self._base_backoff * (2**attempt)
                    log.warning(
                        "jupiter server error %d, retrying in %.1fs (attempt %d/%d)",
                        resp.status_code,
                        delay,
                        attempt + 1,
                        self._max_retries,
                    )
                    last_exc = JupiterAPIError(resp.status_code, resp.text)
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code != 200:
                    raise JupiterAPIError(resp.status_code, resp.text)

                return resp.json()

            except httpx.TimeoutException as exc:
                delay = self._base_backoff * (2**attempt)
                log.warning(
                    "jupiter request timed out, retrying in %.1fs (attempt %d/%d)",
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                last_exc = exc
                await asyncio.sleep(delay)

            except httpx.HTTPError as exc:
                delay = self._base_backoff * (2**attempt)
                log.warning(
                    "jupiter http error: %s, retrying in %.1fs (attempt %d/%d)",
                    exc,
                    delay,
                    attempt + 1,
                    self._max_retries,
                )
                last_exc = exc
                await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]


def _parse_quote(data: dict[str, Any]) -> JupiterQuote:
    route_plan = []
    for step in data.get("routePlan", []):
        si = step["swapInfo"]
        route_plan.append(
            {
                "swap_info": {
                    "amm_key": si["ammKey"],
                    "label": si.get("label", ""),
                    "input_mint": si["inputMint"],
                    "output_mint": si["outputMint"],
                    "in_amount": si["inAmount"],
                    "out_amount": si["outAmount"],
                },
                "percent": step.get("percent"),
            }
        )

    return JupiterQuote(
        input_mint=data["inputMint"],
        output_mint=data["outputMint"],
        in_amount=data["inAmount"],
        out_amount=data["outAmount"],
        other_amount_threshold=data["otherAmountThreshold"],
        swap_mode=data["swapMode"],
        slippage_bps=data["slippageBps"],
        price_impact_pct=data["priceImpactPct"],
        route_plan=route_plan,
        context_slot=data.get("contextSlot"),
        time_taken=data.get("timeTaken"),
    )
