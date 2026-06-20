from __future__ import annotations

import asyncio
import base64
import json
import struct
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from trek.services.errors import (
    InsufficientBalanceError,
    JupiterApiError,
    RpcError,
    SignerError,
    SignerUnavailableError,
    SlippageExceededError,
    TransactionConfirmationError,
    TransactionExpiredError,
)
from trek.services.jupiter_swap import JupiterSwapClient, SwapResult
from trek.services.signer_client import SignerClient
from trek.services.solana_rpc import SolanaRpcClient


SAMPLE_QUOTE = {
    "inputMint": "So11111111111111111111111111111111111111112",
    "outputMint": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "inAmount": "1000000",
    "outAmount": "148500",
    "routePlan": [],
}


class TestJupiterSwapClient:
    @pytest.fixture
    def signer(self):
        return AsyncMock(spec=SignerClient)

    @pytest.fixture
    def rpc(self):
        return AsyncMock(spec=SolanaRpcClient)

    @pytest.fixture
    def client(self, signer, rpc):
        return JupiterSwapClient(signer, rpc)

    @pytest.mark.asyncio
    async def test_execute_swap_success(self, client, signer, rpc):
        swap_tx_b64 = base64.b64encode(b"\x00" * 100).decode()
        signer.sign_transaction.return_value = swap_tx_b64
        rpc.send_transaction.return_value = "5abc123sig"
        rpc.confirm_transaction.return_value = {
            "confirmationStatus": "confirmed",
            "slot": 12345,
        }

        with patch.object(
            client, "_get_swap_transaction",
            return_value=(swap_tx_b64, 999999),
        ), patch("trek.services.jupiter_swap.VersionedTransaction") as mock_vt:
            mock_tx = mock_vt.from_bytes.return_value
            mock_tx.message.instructions.return_value = []
            mock_tx.signatures = []

            result = await client.execute_swap(SAMPLE_QUOTE, "WalletPubkeyHere")

        assert result.signature == "5abc123sig"
        assert result.confirmation_status == "confirmed"
        assert result.slot == 12345
        signer.sign_transaction.assert_awaited_once_with(swap_tx_b64)
        rpc.send_transaction.assert_awaited_once_with(swap_tx_b64)
        rpc.confirm_transaction.assert_awaited_once_with("5abc123sig", 999999)

    @pytest.mark.asyncio
    async def test_get_swap_transaction_success(self, client):
        resp_data = {
            "swapTransaction": "dHhfYmFzZTY0",
            "lastValidBlockHeight": 500000,
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = resp_data

        with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
            tx, height = await client._get_swap_transaction(
                SAMPLE_QUOTE,
                "WalletPubkey",
                dynamic_compute_unit_limit=True,
                prioritization_fee_lamports="auto",
            )

        assert tx == "dHhfYmFzZTY0"
        assert height == 500000

    @pytest.mark.asyncio
    async def test_get_swap_transaction_insufficient_balance(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Insufficient SOL balance for transaction"

        with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
            with pytest.raises(InsufficientBalanceError):
                await client._get_swap_transaction(
                    SAMPLE_QUOTE,
                    "WalletPubkey",
                    dynamic_compute_unit_limit=True,
                    prioritization_fee_lamports="auto",
                )

    @pytest.mark.asyncio
    async def test_get_swap_transaction_slippage_exceeded(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 400
        mock_resp.text = "Slippage tolerance exceeded"

        with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
            with pytest.raises(SlippageExceededError):
                await client._get_swap_transaction(
                    SAMPLE_QUOTE,
                    "WalletPubkey",
                    dynamic_compute_unit_limit=True,
                    prioritization_fee_lamports="auto",
                )

    @pytest.mark.asyncio
    async def test_get_swap_transaction_generic_error(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
            with pytest.raises(JupiterApiError) as exc_info:
                await client._get_swap_transaction(
                    SAMPLE_QUOTE,
                    "WalletPubkey",
                    dynamic_compute_unit_limit=True,
                    prioritization_fee_lamports="auto",
                )
            assert exc_info.value.status_code == 500

    @pytest.mark.asyncio
    async def test_get_swap_transaction_missing_field(self, client):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"lastValidBlockHeight": 100}

        with patch.object(client._http, "post", AsyncMock(return_value=mock_resp)):
            with pytest.raises(JupiterApiError, match="missing swapTransaction"):
                await client._get_swap_transaction(
                    SAMPLE_QUOTE,
                    "WalletPubkey",
                    dynamic_compute_unit_limit=True,
                    prioritization_fee_lamports="auto",
                )


class TestSolanaRpcClient:
    @pytest.fixture
    def rpc(self):
        return SolanaRpcClient(rpc_url="http://localhost:8899")

    @pytest.mark.asyncio
    async def test_send_transaction(self, rpc):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"jsonrpc": "2.0", "id": 1, "result": "txsig123"}
        mock_resp.raise_for_status = MagicMock()

        with patch.object(rpc._client, "post", AsyncMock(return_value=mock_resp)):
            sig = await rpc.send_transaction("base64tx")
        assert sig == "txsig123"

    @pytest.mark.asyncio
    async def test_rpc_error_raises(self, rpc):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "jsonrpc": "2.0",
            "id": 1,
            "error": {"code": -32002, "message": "Transaction simulation failed"},
        }
        mock_resp.raise_for_status = MagicMock()

        with patch.object(rpc._client, "post", AsyncMock(return_value=mock_resp)):
            with pytest.raises(RpcError) as exc_info:
                await rpc.send_transaction("base64tx")
            assert exc_info.value.code == -32002

    @pytest.mark.asyncio
    async def test_confirm_transaction_success(self, rpc):
        with patch.object(rpc, "get_block_height", return_value=100), \
             patch.object(rpc, "get_signature_statuses", return_value=[{
                 "confirmationStatus": "confirmed",
                 "slot": 101,
                 "err": None,
             }]):
            status = await rpc.confirm_transaction("sig123", 200)
        assert status["confirmationStatus"] == "confirmed"

    @pytest.mark.asyncio
    async def test_confirm_transaction_expired(self, rpc):
        with patch.object(rpc, "get_block_height", return_value=201), \
             patch("asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(TransactionExpiredError):
                await rpc.confirm_transaction("sig123", 200)

    @pytest.mark.asyncio
    async def test_confirm_transaction_error(self, rpc):
        with patch.object(rpc, "get_block_height", return_value=100), \
             patch.object(rpc, "get_signature_statuses", return_value=[{
                 "confirmationStatus": "confirmed",
                 "slot": 101,
                 "err": {"InstructionError": [0, "Custom"]},
             }]):
            with pytest.raises(TransactionConfirmationError):
                await rpc.confirm_transaction("sig123", 200)


class TestSignerClient:
    @pytest.mark.asyncio
    async def test_sign_transaction_success(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")
        signed_b64 = base64.b64encode(b"signed_payload").decode()

        async def mock_server(reader, writer):
            length_bytes = await reader.readexactly(4)
            length = struct.unpack(">I", length_bytes)[0]
            await reader.readexactly(length)
            resp = json.dumps({"signed_transaction": signed_b64}).encode()
            writer.write(struct.pack(">I", len(resp)) + resp)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(mock_server, path=socket_path)
        try:
            client = SignerClient(socket_path=socket_path)
            result = await client.sign_transaction("dW5zaWduZWQ=")
            assert result == signed_b64
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_sign_transaction_signer_error(self, tmp_path):
        socket_path = str(tmp_path / "test.sock")

        async def mock_server(reader, writer):
            length_bytes = await reader.readexactly(4)
            length = struct.unpack(">I", length_bytes)[0]
            await reader.readexactly(length)
            resp = json.dumps({"error": "Disallowed program"}).encode()
            writer.write(struct.pack(">I", len(resp)) + resp)
            await writer.drain()
            writer.close()
            await writer.wait_closed()

        server = await asyncio.start_unix_server(mock_server, path=socket_path)
        try:
            client = SignerClient(socket_path=socket_path)
            with pytest.raises(SignerError, match="Disallowed program"):
                await client.sign_transaction("dW5zaWduZWQ=")
        finally:
            server.close()
            await server.wait_closed()

    @pytest.mark.asyncio
    async def test_sign_transaction_unavailable(self):
        client = SignerClient(socket_path="/nonexistent/sock")
        with pytest.raises(SignerUnavailableError):
            await client.sign_transaction("dW5zaWduZWQ=")


class TestSwapErrors:
    def test_jupiter_api_error(self):
        err = JupiterApiError(400, "bad request")
        assert err.status_code == 400
        assert "400" in str(err)

    def test_transaction_expired_error(self):
        err = TransactionExpiredError("sig123", 999)
        assert err.signature == "sig123"
        assert err.last_valid_block_height == 999

    def test_rpc_error(self):
        err = RpcError("sendTransaction", -32002, "failed")
        assert err.method == "sendTransaction"
        assert err.code == -32002

    def test_error_hierarchy(self):
        from trek.services.errors import SwapError
        assert issubclass(JupiterApiError, SwapError)
        assert issubclass(InsufficientBalanceError, SwapError)
        assert issubclass(SlippageExceededError, SwapError)
        assert issubclass(SignerError, SwapError)
        assert issubclass(TransactionExpiredError, SwapError)
        assert issubclass(TransactionConfirmationError, SwapError)
        assert issubclass(RpcError, SwapError)
