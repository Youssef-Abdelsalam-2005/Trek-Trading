import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from backend.app.models.backtest_run import BacktestRun
from backend.app.models.enums import TradeDirection, TradeSource
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.models.trade import Trade
from trek.api import app
from trek.database import get_session


def _make_variation(variation_id: uuid.UUID) -> StrategyVariation:
    v = MagicMock(spec=StrategyVariation)
    v.id = variation_id
    return v


def _make_backtest(
    backtest_id: uuid.UUID,
    variation_id: uuid.UUID,
    has_error: bool = False,
) -> BacktestRun:
    now = datetime.now(timezone.utc)
    bt = MagicMock(spec=BacktestRun)
    bt.id = backtest_id
    bt.variation_id = variation_id
    bt.start_date = datetime(2025, 1, 1, tzinfo=timezone.utc)
    bt.end_date = datetime(2025, 6, 1, tzinfo=timezone.utc)
    bt.sortino_ratio = 1.5
    bt.sharpe_ratio = 1.2
    bt.max_drawdown = -0.15
    bt.total_return = 0.42
    bt.win_rate = 0.55
    bt.trade_count = 120
    bt.equity_curve = [
        {"time": "2025-01-01", "value": 10000},
        {"time": "2025-03-01", "value": 12000},
        {"time": "2025-06-01", "value": 14200},
    ]
    bt.has_error = has_error
    bt.error_message = "timeout" if has_error else None
    bt.duration_seconds = 12.5
    bt.metrics = {"profit_factor": 1.8}
    bt.created_at = now
    bt.updated_at = now
    return bt


def _make_trade(trade_id: uuid.UUID, variation_id: uuid.UUID) -> Trade:
    now = datetime.now(timezone.utc)
    t = MagicMock(spec=Trade)
    t.id = trade_id
    t.variation_id = variation_id
    t.source = TradeSource.BACKTEST
    t.direction = TradeDirection.BUY
    t.pair = "SOL/USDC"
    t.price = 120.5
    t.quantity = 10.0
    t.value_usd = 1205.0
    t.fee_usd = 0.5
    t.slippage_bps = 3.2
    t.tx_signature = None
    t.executed_at = datetime(2025, 2, 15, tzinfo=timezone.utc)
    t.created_at = now
    t.updated_at = now
    return t


class FakeSession:
    def __init__(self):
        self._get_returns = {}
        self._execute_results = []

    def configure_get(self, model_cls, obj_id, result):
        self._get_returns[(model_cls, obj_id)] = result

    def add_execute_result(self, rows):
        self._execute_results.append(rows)

    async def get(self, model_cls, obj_id):
        return self._get_returns.get((model_cls, obj_id))

    async def execute(self, stmt):
        rows = self._execute_results.pop(0) if self._execute_results else []
        result = MagicMock()
        result.scalars.return_value.all.return_value = rows
        return result


@pytest.fixture
def fake_session():
    return FakeSession()


@pytest.fixture
def client(fake_session):
    app.dependency_overrides[get_session] = lambda: fake_session
    yield TestClient(app)
    app.dependency_overrides.clear()


class TestListVariationBacktests:
    def test_returns_empty_list(self, client, fake_session):
        vid = uuid.uuid4()
        fake_session.configure_get(StrategyVariation, vid, _make_variation(vid))
        fake_session.add_execute_result([])

        resp = client.get(f"/api/variations/{vid}/backtests")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_backtest_summaries(self, client, fake_session):
        vid = uuid.uuid4()
        bt = _make_backtest(uuid.uuid4(), vid)
        fake_session.configure_get(StrategyVariation, vid, _make_variation(vid))
        fake_session.add_execute_result([bt])

        resp = client.get(f"/api/variations/{vid}/backtests")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["sortino_ratio"] == 1.5
        assert data[0]["total_return"] == 0.42
        assert "equity_curve" not in data[0]

    def test_variation_not_found(self, client, fake_session):
        vid = uuid.uuid4()
        resp = client.get(f"/api/variations/{vid}/backtests")
        assert resp.status_code == 404

    def test_error_backtest_included(self, client, fake_session):
        vid = uuid.uuid4()
        bt = _make_backtest(uuid.uuid4(), vid, has_error=True)
        fake_session.configure_get(StrategyVariation, vid, _make_variation(vid))
        fake_session.add_execute_result([bt])

        resp = client.get(f"/api/variations/{vid}/backtests")
        assert resp.status_code == 200
        assert resp.json()[0]["has_error"] is True
        assert resp.json()[0]["error_message"] == "timeout"


class TestGetBacktestDetail:
    def test_returns_detail_with_equity_curve_and_trades(self, client, fake_session):
        vid = uuid.uuid4()
        bt_id = uuid.uuid4()
        trade_id = uuid.uuid4()
        bt = _make_backtest(bt_id, vid)
        trade = _make_trade(trade_id, vid)
        fake_session.configure_get(BacktestRun, bt_id, bt)
        fake_session.add_execute_result([trade])

        resp = client.get(f"/api/backtests/{bt_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == str(bt_id)
        assert len(data["equity_curve"]) == 3
        assert data["equity_curve"][0]["time"] == "2025-01-01"
        assert len(data["trades"]) == 1
        assert data["trades"][0]["direction"] == "buy"
        assert data["trades"][0]["price"] == 120.5

    def test_backtest_not_found(self, client, fake_session):
        bt_id = uuid.uuid4()
        resp = client.get(f"/api/backtests/{bt_id}")
        assert resp.status_code == 404

    def test_detail_with_no_trades(self, client, fake_session):
        vid = uuid.uuid4()
        bt_id = uuid.uuid4()
        bt = _make_backtest(bt_id, vid)
        fake_session.configure_get(BacktestRun, bt_id, bt)
        fake_session.add_execute_result([])

        resp = client.get(f"/api/backtests/{bt_id}")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trades"] == []
        assert data["equity_curve"] is not None
