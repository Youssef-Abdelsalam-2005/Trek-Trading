from __future__ import annotations

import asyncio
import base64
import logging
from typing import Any

import httpx

from trek.services.errors import RpcError, TransactionConfirmationError, TransactionExpiredError

log = logging.getLogger(__name__)

DEFAULT_RPC_URL = "https://api.mainnet-beta.solana.com"
CONFIRM_POLL_INTERVAL = 2.0
CONFIRM_MAX_POLLS = 90


class SolanaRpcClient:
    def __init__(
        self,
        rpc_url: str = DEFAULT_RPC_URL,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._rpc_url = rpc_url
        self._client = httpx.AsyncClient(timeout=timeout)
        self._request_id = 0

    async def close(self) -> None:
        await self._client.aclose()

    async def _call(self, method: str, params: list[Any] | None = None) -> Any:
        self._request_id += 1
        body = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params or [],
        }
        resp = await self._client.post(self._rpc_url, json=body)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            err = data["error"]
            raise RpcError(method, err.get("code"), err.get("message", str(err)))
        return data.get("result")

    async def send_transaction(self, signed_tx_b64: str) -> str:
        result = await self._call(
            "sendTransaction",
            [
                signed_tx_b64,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 0,
                },
            ],
        )
        log.info("Transaction sent: %s", result)
        return result

    async def get_block_height(self) -> int:
        return await self._call("getBlockHeight", [{"commitment": "confirmed"}])

    async def get_signature_statuses(
        self, signatures: list[str],
    ) -> list[dict[str, Any] | None]:
        result = await self._call(
            "getSignatureStatuses",
            [signatures, {"searchTransactionHistory": True}],
        )
        return result["value"]

    async def confirm_transaction(
        self,
        signature: str,
        last_valid_block_height: int,
    ) -> dict[str, Any]:
        for poll in range(CONFIRM_MAX_POLLS):
            await asyncio.sleep(CONFIRM_POLL_INTERVAL)

            block_height = await self.get_block_height()
            if block_height > last_valid_block_height:
                raise TransactionExpiredError(signature, last_valid_block_height)

            statuses = await self.get_signature_statuses([signature])
            status = statuses[0] if statuses else None
            if status is None:
                log.debug(
                    "Poll %d/%d: signature %s not found yet (block %d / %d)",
                    poll + 1, CONFIRM_MAX_POLLS, signature,
                    block_height, last_valid_block_height,
                )
                continue

            if status.get("err"):
                raise TransactionConfirmationError(
                    signature, f"transaction error: {status['err']}"
                )

            confirmation = status.get("confirmationStatus")
            if confirmation in ("confirmed", "finalized"):
                log.info(
                    "Transaction %s %s at slot %s",
                    signature, confirmation, status.get("slot"),
                )
                return status

            log.debug(
                "Poll %d/%d: signature %s status=%s",
                poll + 1, CONFIRM_MAX_POLLS, signature, confirmation,
            )

        raise TransactionConfirmationError(
            signature,
            f"not confirmed after {CONFIRM_MAX_POLLS} polls "
            f"({CONFIRM_MAX_POLLS * CONFIRM_POLL_INTERVAL:.0f}s)",
        )
