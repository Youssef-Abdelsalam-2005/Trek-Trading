from __future__ import annotations

import base64
import logging
from dataclasses import dataclass
from typing import Any

import httpx
from solders.transaction import VersionedTransaction

from trek.services.errors import (
    InsufficientBalanceError,
    JupiterApiError,
    SlippageExceededError,
    SwapError,
)
from trek.services.signer_client import SignerClient
from trek.services.solana_rpc import SolanaRpcClient

log = logging.getLogger(__name__)

JUPITER_SWAP_URL = "https://api.jup.ag/swap/v1/swap"


@dataclass(frozen=True)
class SwapResult:
    signature: str
    confirmation_status: str
    slot: int | None
    input_mint: str
    output_mint: str
    in_amount: str
    out_amount: str


class JupiterSwapClient:
    def __init__(
        self,
        signer: SignerClient,
        rpc: SolanaRpcClient,
        *,
        jupiter_url: str = JUPITER_SWAP_URL,
        http_timeout: float = 30.0,
    ) -> None:
        self._signer = signer
        self._rpc = rpc
        self._jupiter_url = jupiter_url
        self._http = httpx.AsyncClient(timeout=http_timeout)

    async def close(self) -> None:
        await self._http.aclose()

    async def execute_swap(
        self,
        quote_response: dict[str, Any],
        user_public_key: str,
        *,
        dynamic_compute_unit_limit: bool = True,
        prioritization_fee_lamports: str | int = "auto",
    ) -> SwapResult:
        log.info(
            "Executing swap: %s %s -> %s %s for wallet %s",
            quote_response.get("inAmount"),
            quote_response.get("inputMint"),
            quote_response.get("outAmount"),
            quote_response.get("outputMint"),
            user_public_key,
        )

        swap_tx_b64, last_valid_block_height = await self._get_swap_transaction(
            quote_response,
            user_public_key,
            dynamic_compute_unit_limit=dynamic_compute_unit_limit,
            prioritization_fee_lamports=prioritization_fee_lamports,
        )

        _tx = VersionedTransaction.from_bytes(base64.b64decode(swap_tx_b64))
        log.info(
            "Deserialized VersionedTransaction: %d instructions, %d signatures",
            len(_tx.message.instructions()),
            len(_tx.signatures),
        )

        signed_tx_b64 = await self._signer.sign_transaction(swap_tx_b64)

        signature = await self._rpc.send_transaction(signed_tx_b64)

        status = await self._rpc.confirm_transaction(signature, last_valid_block_height)

        return SwapResult(
            signature=signature,
            confirmation_status=status.get("confirmationStatus", "unknown"),
            slot=status.get("slot"),
            input_mint=quote_response.get("inputMint", ""),
            output_mint=quote_response.get("outputMint", ""),
            in_amount=quote_response.get("inAmount", ""),
            out_amount=quote_response.get("outAmount", ""),
        )

    async def _get_swap_transaction(
        self,
        quote_response: dict[str, Any],
        user_public_key: str,
        *,
        dynamic_compute_unit_limit: bool,
        prioritization_fee_lamports: str | int,
    ) -> tuple[str, int]:
        payload = {
            "quoteResponse": quote_response,
            "userPublicKey": user_public_key,
            "dynamicComputeUnitLimit": dynamic_compute_unit_limit,
            "prioritizationFeeLamports": prioritization_fee_lamports,
        }

        resp = await self._http.post(self._jupiter_url, json=payload)

        if resp.status_code != 200:
            body = resp.text
            if "insufficient" in body.lower() or "balance" in body.lower():
                raise InsufficientBalanceError(body)
            if "slippage" in body.lower():
                raise SlippageExceededError(body)
            raise JupiterApiError(resp.status_code, body)

        data = resp.json()

        swap_tx = data.get("swapTransaction")
        if not swap_tx:
            raise JupiterApiError(resp.status_code, "response missing swapTransaction")

        last_valid_block_height = data.get("lastValidBlockHeight")
        if last_valid_block_height is None:
            raise JupiterApiError(
                resp.status_code, "response missing lastValidBlockHeight"
            )

        log.info("Got swap transaction (lastValidBlockHeight=%d)", last_valid_block_height)
        return swap_tx, last_valid_block_height
