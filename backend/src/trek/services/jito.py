from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

import httpx

from backend.app.schemas.jito import (
    BundleStatus,
    BundleStatusResponse,
    BundleSubmitResult,
    SubmissionPath,
    TransactionSubmitResult,
)

log = logging.getLogger(__name__)

DEFAULT_BLOCK_ENGINE_URL = "https://mainnet.block-engine.jito.wtf"
DEFAULT_TIP_LAMPORTS = 5_000_000  # 0.005 SOL

JITO_TIP_ACCOUNTS = [
    "96gYZGLnJYVFmbjzopPSU6QiEV5fGqZNyN9nmNhvrZU5",
    "HFqU5x63VTqvQss8hp11i4bVqkfRtQ7NmsXkpe321gVb",
    "Cw8CFyM9FkoMi7K7Crf6HNQqf4uEMzpKw6QNghXLvLkY",
    "ADaUMid9yfUytqMBgopwjb2DTLSLxXLdCpNzYAsVpHp2",
    "DfXygSm4jCyNCybVYYK6DwvWqjKee8pbDmJGcLWNDXjh",
    "ADuUkR4vqLUMWXxW9gh6D6L8pMSawimctcNZ5pGwDcEt",
    "DttWaMuVvTiduZRnguLF7jNxTgiMBZ1hyAumKUiL2KRL",
    "3AVi9Tg9Uo68tJfuvoKvqKNWKkC5wPdSSdeBnizKZ6jT",
]

_BUNDLE_STATUS_POLL_INTERVAL = 2.0
_BUNDLE_STATUS_MAX_POLLS = 15


class JitoBundleError(Exception):
    def __init__(self, message: str, code: int | None = None):
        self.code = code
        super().__init__(message)


class JitoBundleClient:
    def __init__(
        self,
        *,
        block_engine_url: str = DEFAULT_BLOCK_ENGINE_URL,
        tip_lamports: int = DEFAULT_TIP_LAMPORTS,
        timeout_seconds: float = 15.0,
        max_retries: int = 2,
        base_backoff_seconds: float = 1.0,
        solana_rpc_url: str = "https://api.mainnet-beta.solana.com",
    ):
        self._block_engine_url = block_engine_url.rstrip("/")
        self._tip_lamports = tip_lamports
        self._max_retries = max_retries
        self._base_backoff = base_backoff_seconds
        self._solana_rpc_url = solana_rpc_url
        self._client = httpx.AsyncClient(timeout=httpx.Timeout(timeout_seconds))

    @property
    def tip_lamports(self) -> int:
        return self._tip_lamports

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> JitoBundleClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def send_bundle(
        self, serialized_transactions: list[str]
    ) -> BundleSubmitResult:
        """Submit a bundle of base58-encoded serialized transactions to Jito.

        Returns the bundle ID on successful submission.
        """
        payload = self._jsonrpc("sendBundle", [serialized_transactions])
        data = await self._post_jito(payload)
        bundle_id = data["result"]
        log.info("jito bundle submitted: %s", bundle_id)
        return BundleSubmitResult(bundle_id=bundle_id)

    async def get_bundle_status(
        self, bundle_id: str
    ) -> BundleStatusResponse:
        """Query the status of a previously submitted bundle."""
        payload = self._jsonrpc("getBundleStatuses", [[bundle_id]])
        data = await self._post_jito(payload)

        statuses = data.get("result", {}).get("value", [])
        if not statuses:
            return BundleStatusResponse(
                bundle_id=bundle_id, status=BundleStatus.PENDING
            )

        entry = statuses[0]
        status_str = entry.get("confirmation_status", "")
        landed_slot = entry.get("slot")
        err = entry.get("err")

        if status_str in ("processed", "confirmed", "finalized"):
            return BundleStatusResponse(
                bundle_id=bundle_id,
                status=BundleStatus.LANDED,
                landed_slot=landed_slot,
            )

        if err:
            return BundleStatusResponse(
                bundle_id=bundle_id,
                status=BundleStatus.FAILED,
                error=str(err),
            )

        return BundleStatusResponse(
            bundle_id=bundle_id, status=BundleStatus.PENDING
        )

    async def submit_and_monitor(
        self, serialized_transactions: list[str]
    ) -> BundleStatusResponse:
        """Submit a bundle and poll until it lands or fails."""
        result = await self.send_bundle(serialized_transactions)
        return await self._poll_status(result.bundle_id)

    async def submit_with_fallback(
        self,
        serialized_transactions: list[str],
        swap_tx_base64: str,
    ) -> TransactionSubmitResult:
        """Submit via Jito bundle, falling back to direct RPC on failure.

        Args:
            serialized_transactions: Base58-encoded txs for the Jito bundle
                (swap + tip).
            swap_tx_base64: Base64-encoded swap transaction for direct RPC
                fallback (no tip needed).
        """
        try:
            status = await self.submit_and_monitor(serialized_transactions)

            if status.status == BundleStatus.LANDED:
                return TransactionSubmitResult(
                    path=SubmissionPath.JITO,
                    bundle_id=status.bundle_id,
                    status=status.status,
                )

            if status.status in (BundleStatus.FAILED, BundleStatus.INVALID):
                log.warning(
                    "jito bundle %s failed (%s: %s), falling back to direct RPC",
                    status.bundle_id,
                    status.status.value,
                    status.error,
                )
                return await self._submit_direct_rpc(swap_tx_base64)

            # Ambiguous / still pending after max polls — do NOT retry (C2)
            log.warning(
                "jito bundle %s status ambiguous after polling: %s",
                status.bundle_id,
                status.status.value,
            )
            return TransactionSubmitResult(
                path=SubmissionPath.JITO,
                bundle_id=status.bundle_id,
                status=status.status,
            )

        except (httpx.HTTPError, JitoBundleError) as exc:
            log.warning(
                "jito submission failed (%s), falling back to direct RPC",
                exc,
            )
            return await self._submit_direct_rpc(swap_tx_base64)

    async def _submit_direct_rpc(
        self, tx_base64: str
    ) -> TransactionSubmitResult:
        """Submit a transaction directly via Solana RPC."""
        payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "sendTransaction",
            "params": [
                tx_base64,
                {"encoding": "base64", "skipPreflight": False},
            ],
        }
        resp = await self._client.post(self._solana_rpc_url, json=payload)
        if resp.status_code != 200:
            raise JitoBundleError(
                f"RPC HTTP error {resp.status_code}"
            )
        data = resp.json()

        if "error" in data:
            err = data["error"]
            code = err.get("code") if isinstance(err, dict) else None
            raise JitoBundleError(
                f"RPC sendTransaction failed: {err}", code=code,
            )

        signature = data["result"]
        log.info("direct RPC submission succeeded: %s", signature)
        return TransactionSubmitResult(
            path=SubmissionPath.DIRECT_RPC,
            tx_signature=signature,
        )

    async def _poll_status(self, bundle_id: str) -> BundleStatusResponse:
        for i in range(_BUNDLE_STATUS_MAX_POLLS):
            await asyncio.sleep(_BUNDLE_STATUS_POLL_INTERVAL)
            status = await self.get_bundle_status(bundle_id)
            log.info(
                "bundle %s poll %d/%d: %s",
                bundle_id, i + 1, _BUNDLE_STATUS_MAX_POLLS, status.status.value,
            )
            if status.status != BundleStatus.PENDING:
                return status
        return status

    async def _post_jito(self, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._block_engine_url}/api/v1/bundles"
        last_exc: Exception | None = None

        for attempt in range(self._max_retries + 1):
            try:
                resp = await self._client.post(url, json=payload)

                if resp.status_code == 429:
                    last_exc = JitoBundleError(
                        f"Jito rate limited after {attempt + 1} attempts",
                        code=429,
                    )
                    delay = self._base_backoff * (2**attempt)
                    log.warning(
                        "jito rate limited, retrying in %.1fs (attempt %d/%d)",
                        delay, attempt + 1, self._max_retries,
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code >= 500:
                    delay = self._base_backoff * (2**attempt)
                    log.warning(
                        "jito server error %d, retrying in %.1fs (attempt %d/%d)",
                        resp.status_code, delay, attempt + 1, self._max_retries,
                    )
                    last_exc = JitoBundleError(
                        f"Jito server error {resp.status_code}"
                    )
                    await asyncio.sleep(delay)
                    continue

                if resp.status_code != 200:
                    raise JitoBundleError(
                        f"Jito unexpected status {resp.status_code}"
                    )
                data = resp.json()

                if "error" in data:
                    err = data["error"]
                    code = err.get("code") if isinstance(err, dict) else None
                    raise JitoBundleError(
                        f"Jito RPC error: {err}", code=code,
                    )

                return data

            except httpx.TimeoutException as exc:
                delay = self._base_backoff * (2**attempt)
                log.warning(
                    "jito request timed out, retrying in %.1fs (attempt %d/%d)",
                    delay, attempt + 1, self._max_retries,
                )
                last_exc = exc
                await asyncio.sleep(delay)

            except httpx.HTTPError as exc:
                delay = self._base_backoff * (2**attempt)
                log.warning(
                    "jito http error: %s, retrying in %.1fs (attempt %d/%d)",
                    exc, delay, attempt + 1, self._max_retries,
                )
                last_exc = exc
                await asyncio.sleep(delay)

        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _jsonrpc(method: str, params: list[Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": params,
        }
