import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from backend.app.models.base import Base
from backend.app.models.wallet_state import WalletState
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


class TestWalletStateModel:
    def test_round_trip(self, session):
        now = datetime.now(timezone.utc)
        state = WalletState(
            wallet_address="So11111111111111111111111111111111111111112",
            sol_balance=12.5,
            usdc_balance=500.0,
            snapshot_at=now,
        )
        session.add(state)
        session.commit()

        loaded = session.get(WalletState, state.id)
        assert loaded is not None
        assert loaded.wallet_address == "So11111111111111111111111111111111111111112"
        assert loaded.sol_balance == 12.5
        assert loaded.usdc_balance == 500.0
        assert loaded.snapshot_at.replace(tzinfo=None) == now.replace(tzinfo=None)

    def test_multiple_snapshots_ordered(self, session):
        addr = "So11111111111111111111111111111111111111112"
        for i in range(3):
            state = WalletState(
                wallet_address=addr,
                sol_balance=10.0 + i,
                usdc_balance=100.0 + i,
                snapshot_at=datetime(2026, 4, 14, i, 0, 0, tzinfo=timezone.utc),
            )
            session.add(state)
        session.commit()

        results = (
            session.query(WalletState)
            .filter_by(wallet_address=addr)
            .order_by(WalletState.snapshot_at.desc())
            .all()
        )
        assert len(results) == 3
        assert results[0].sol_balance == 12.0


class TestWalletTrackerFetchBalances:
    @pytest.mark.asyncio
    async def test_fetch_balances_parses_rpc_response(self):
        from trek.services.wallet_tracker import WalletTracker

        mock_pool = AsyncMock()
        tracker = WalletTracker(
            pool=mock_pool,
            rpc_url="https://fake-rpc.test",
            wallet_address="FakeAddress123",
        )

        sol_response = {"jsonrpc": "2.0", "id": 1, "result": {"value": 5_000_000_000}}
        usdc_response = {
            "jsonrpc": "2.0",
            "id": 1,
            "result": {
                "value": [
                    {
                        "account": {
                            "data": {
                                "parsed": {
                                    "info": {
                                        "tokenAmount": {
                                            "amount": "250000000",
                                            "decimals": 6,
                                        }
                                    }
                                }
                            }
                        }
                    }
                ]
            },
        }

        mock_response_sol = MagicMock()
        mock_response_sol.json.return_value = sol_response
        mock_response_sol.raise_for_status = lambda: None

        mock_response_usdc = MagicMock()
        mock_response_usdc.json.return_value = usdc_response
        mock_response_usdc.raise_for_status = lambda: None

        call_count = 0

        async def mock_post(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            body = kwargs.get("json", {})
            if body.get("method") == "getBalance":
                return mock_response_sol
            return mock_response_usdc

        with patch("trek.services.wallet_tracker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            sol, usdc = await tracker.fetch_balances()

        assert sol == 5.0
        assert usdc == 250.0

    @pytest.mark.asyncio
    async def test_fetch_balances_no_usdc_account(self):
        from trek.services.wallet_tracker import WalletTracker

        mock_pool = AsyncMock()
        tracker = WalletTracker(
            pool=mock_pool,
            rpc_url="https://fake-rpc.test",
            wallet_address="FakeAddress123",
        )

        sol_response = {"jsonrpc": "2.0", "id": 1, "result": {"value": 1_000_000_000}}
        usdc_response = {"jsonrpc": "2.0", "id": 1, "result": {"value": []}}

        mock_response_sol = MagicMock()
        mock_response_sol.json.return_value = sol_response
        mock_response_sol.raise_for_status = lambda: None

        mock_response_usdc = MagicMock()
        mock_response_usdc.json.return_value = usdc_response
        mock_response_usdc.raise_for_status = lambda: None

        async def mock_post(*args, **kwargs):
            body = kwargs.get("json", {})
            if body.get("method") == "getBalance":
                return mock_response_sol
            return mock_response_usdc

        with patch("trek.services.wallet_tracker.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = mock_post
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            sol, usdc = await tracker.fetch_balances()

        assert sol == 1.0
        assert usdc == 0.0
