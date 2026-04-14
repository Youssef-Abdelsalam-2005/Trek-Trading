from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from backend.app.schemas.jito import BundleStatus, SubmissionPath
from trek.services.jito import (
    DEFAULT_BLOCK_ENGINE_URL,
    JITO_TIP_ACCOUNTS,
    JitoBundleClient,
    JitoBundleError,
)

FAKE_BUNDLE_ID = "abc123bundleid"
FAKE_TX_SIGNATURE = "5KtPn1LGuxhFiwjxErkxTb3gTaKsGPM3Y..."


def _jito_ok(result):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": result})


def _jito_error(code, message):
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": "1", "error": {"code": code, "message": message}},
    )


def _status_response(confirmation_status, slot=None, err=None):
    entry = {"bundle_id": FAKE_BUNDLE_ID, "confirmation_status": confirmation_status}
    if slot is not None:
        entry["slot"] = slot
    if err is not None:
        entry["err"] = err
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": "1", "result": {"value": [entry]}},
    )


def _rpc_ok(signature):
    return httpx.Response(200, json={"jsonrpc": "2.0", "id": "1", "result": signature})


def _rpc_error(code, message):
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": "1", "error": {"code": code, "message": message}},
    )


@pytest.fixture
def client():
    return JitoBundleClient(
        tip_lamports=5_000_000,
        max_retries=0,
        base_backoff_seconds=0.01,
    )


class TestSendBundle:
    async def test_successful_submission(self, client: JitoBundleClient):
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=_jito_ok(FAKE_BUNDLE_ID)
        ):
            result = await client.send_bundle(["tx1_base58", "tx2_base58"])
            assert result.bundle_id == FAKE_BUNDLE_ID

    async def test_rpc_error_raises(self, client: JitoBundleClient):
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=_jito_error(-32000, "bad bundle")
        ):
            with pytest.raises(JitoBundleError, match="bad bundle"):
                await client.send_bundle(["tx1"])


class TestGetBundleStatus:
    async def test_landed(self, client: JitoBundleClient):
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=_status_response("finalized", slot=12345)
        ):
            status = await client.get_bundle_status(FAKE_BUNDLE_ID)
            assert status.status == BundleStatus.LANDED
            assert status.landed_slot == 12345

    async def test_confirmed(self, client: JitoBundleClient):
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=_status_response("confirmed", slot=99)
        ):
            status = await client.get_bundle_status(FAKE_BUNDLE_ID)
            assert status.status == BundleStatus.LANDED

    async def test_failed_with_error(self, client: JitoBundleClient):
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=_status_response("", err={"msg": "slippage"})
        ):
            status = await client.get_bundle_status(FAKE_BUNDLE_ID)
            assert status.status == BundleStatus.FAILED

    async def test_pending_empty_result(self, client: JitoBundleClient):
        resp = httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "1", "result": {"value": []}},
        )
        with patch.object(client._client, "post", new_callable=AsyncMock, return_value=resp):
            status = await client.get_bundle_status(FAKE_BUNDLE_ID)
            assert status.status == BundleStatus.PENDING


class TestSubmitWithFallback:
    async def test_jito_lands_successfully(self, client: JitoBundleClient):
        submit_resp = _jito_ok(FAKE_BUNDLE_ID)
        status_resp = _status_response("finalized", slot=100)

        with patch.object(
            client._client, "post", new_callable=AsyncMock, side_effect=[submit_resp, status_resp]
        ):
            result = await client.submit_with_fallback(
                ["tx1_base58"], swap_tx_base64="base64swap"
            )
            assert result.path == SubmissionPath.JITO
            assert result.bundle_id == FAKE_BUNDLE_ID
            assert result.status == BundleStatus.LANDED

    async def test_jito_fails_falls_back_to_rpc(self, client: JitoBundleClient):
        submit_resp = _jito_ok(FAKE_BUNDLE_ID)
        status_resp = _status_response("", err={"msg": "dropped"})
        rpc_resp = _rpc_ok(FAKE_TX_SIGNATURE)

        with patch.object(
            client._client, "post", new_callable=AsyncMock, side_effect=[submit_resp, status_resp, rpc_resp]
        ):
            result = await client.submit_with_fallback(
                ["tx1_base58"], swap_tx_base64="base64swap"
            )
            assert result.path == SubmissionPath.DIRECT_RPC
            assert result.tx_signature == FAKE_TX_SIGNATURE

    async def test_jito_connection_error_falls_back(self, client: JitoBundleClient):
        with patch.object(
            client._client,
            "post",
            new_callable=AsyncMock,
            side_effect=[httpx.ConnectError("unreachable"), _rpc_ok(FAKE_TX_SIGNATURE)],
        ):
            result = await client.submit_with_fallback(
                ["tx1_base58"], swap_tx_base64="base64swap"
            )
            assert result.path == SubmissionPath.DIRECT_RPC

    async def test_ambiguous_status_not_retried(self, client: JitoBundleClient):
        """C2: ambiguous state is surfaced, not retried."""
        submit_resp = _jito_ok(FAKE_BUNDLE_ID)
        # All polls return pending
        pending_resp = httpx.Response(
            200,
            json={"jsonrpc": "2.0", "id": "1", "result": {"value": []}},
        )

        with patch(
            "trek.services.jito._BUNDLE_STATUS_MAX_POLLS", 1
        ), patch(
            "trek.services.jito._BUNDLE_STATUS_POLL_INTERVAL", 0.01
        ), patch.object(
            client._client, "post", new_callable=AsyncMock, side_effect=[submit_resp, pending_resp]
        ):
            result = await client.submit_with_fallback(
                ["tx1_base58"], swap_tx_base64="base64swap"
            )
            assert result.path == SubmissionPath.JITO
            assert result.status == BundleStatus.PENDING


class TestDirectRpcFallback:
    async def test_rpc_error_raises(self, client: JitoBundleClient):
        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=_rpc_error(-32002, "blockhash expired")
        ):
            with pytest.raises(JitoBundleError, match="blockhash expired"):
                await client._submit_direct_rpc("base64swap")


class TestRetry:
    async def test_rate_limit_retry(self):
        client = JitoBundleClient(max_retries=1, base_backoff_seconds=0.01)
        rate_limited = httpx.Response(429)
        ok = _jito_ok(FAKE_BUNDLE_ID)

        with patch.object(
            client._client, "post", new_callable=AsyncMock, side_effect=[rate_limited, ok]
        ):
            result = await client.send_bundle(["tx1"])
            assert result.bundle_id == FAKE_BUNDLE_ID

    async def test_server_error_retry(self):
        client = JitoBundleClient(max_retries=1, base_backoff_seconds=0.01)
        error_500 = httpx.Response(500)
        ok = _jito_ok(FAKE_BUNDLE_ID)

        with patch.object(
            client._client, "post", new_callable=AsyncMock, side_effect=[error_500, ok]
        ):
            result = await client.send_bundle(["tx1"])
            assert result.bundle_id == FAKE_BUNDLE_ID

    async def test_timeout_retry(self):
        client = JitoBundleClient(max_retries=1, base_backoff_seconds=0.01)
        ok = _jito_ok(FAKE_BUNDLE_ID)

        with patch.object(
            client._client,
            "post",
            new_callable=AsyncMock,
            side_effect=[httpx.ReadTimeout("timeout"), ok],
        ):
            result = await client.send_bundle(["tx1"])
            assert result.bundle_id == FAKE_BUNDLE_ID

    async def test_429_exhaustion_raises_jito_error(self):
        client = JitoBundleClient(max_retries=1, base_backoff_seconds=0.01)
        rate_limited = httpx.Response(429)

        with patch.object(
            client._client, "post", new_callable=AsyncMock, return_value=rate_limited
        ):
            with pytest.raises(JitoBundleError, match="rate limited"):
                await client.send_bundle(["tx1"])

    async def test_429_exhaustion_triggers_fallback(self):
        client = JitoBundleClient(max_retries=0, base_backoff_seconds=0.01)
        rate_limited = httpx.Response(429)
        rpc_resp = _rpc_ok(FAKE_TX_SIGNATURE)

        with patch.object(
            client._client, "post", new_callable=AsyncMock, side_effect=[rate_limited, rpc_resp]
        ):
            result = await client.submit_with_fallback(
                ["tx1_base58"], swap_tx_base64="base64swap"
            )
            assert result.path == SubmissionPath.DIRECT_RPC
            assert result.tx_signature == FAKE_TX_SIGNATURE


class TestTipAccounts:
    def test_eight_tip_accounts(self):
        assert len(JITO_TIP_ACCOUNTS) == 8

    def test_tip_accounts_are_base58(self):
        for acct in JITO_TIP_ACCOUNTS:
            assert len(acct) >= 32
            assert all(c.isalnum() for c in acct)


class TestConfiguration:
    def test_default_tip(self):
        client = JitoBundleClient()
        assert client.tip_lamports == 5_000_000

    def test_custom_tip(self):
        client = JitoBundleClient(tip_lamports=10_000_000)
        assert client.tip_lamports == 10_000_000

    async def test_context_manager(self):
        async with JitoBundleClient() as c:
            assert c.tip_lamports == 5_000_000
