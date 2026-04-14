from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.models.base import Base
from backend.app.models.enums import StrategyStatus
from backend.app.models.experiment import Experiment
from backend.app.models.live_deployment import LiveDeployment
from backend.app.models.risk_config import RiskConfig
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.models.wallet_state import WalletState
from trek.api import app
from trek.database import get_session

TEST_DB_URL = "sqlite+aiosqlite:///:memory:"

engine = create_async_engine(TEST_DB_URL, echo=False)
test_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def override_get_session():
    async with test_session_factory() as session:
        yield session


app.dependency_overrides[get_session] = override_get_session


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def session():
    async with test_session_factory() as s:
        yield s


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def _create_experiment(session: AsyncSession) -> uuid.UUID:
    exp = Experiment(name="test-experiment")
    session.add(exp)
    await session.commit()
    await session.refresh(exp)
    return exp.id


async def _create_variation(
    session: AsyncSession, experiment_id: uuid.UUID, status: StrategyStatus
) -> uuid.UUID:
    var = StrategyVariation(
        experiment_id=experiment_id,
        code="def generate_signal(): pass",
        status=status,
    )
    session.add(var)
    await session.commit()
    await session.refresh(var)
    return var.id


async def _create_risk_config(session: AsyncSession, **overrides) -> uuid.UUID:
    defaults = dict(
        label="global",
        is_active=True,
        max_position_size_usd=100.0,
        max_drawdown_pct=0.15,
        max_daily_loss_usd=50.0,
        max_concurrent_live=3,
        portfolio_stop_loss_pct=0.25,
        per_strategy_stop_loss_pct=0.15,
        paper_trading_duration_hours=168,
        min_sortino_threshold=1.5,
        max_max_drawdown_pct=0.30,
    )
    defaults.update(overrides)
    rc = RiskConfig(**defaults)
    session.add(rc)
    await session.commit()
    await session.refresh(rc)
    return rc.id


async def _create_wallet(session: AsyncSession, sol: float = 1000.0, usdc: float = 500.0) -> uuid.UUID:
    ws = WalletState(
        wallet_address="test_wallet_addr",
        sol_balance=sol,
        usdc_balance=usdc,
        snapshot_at=datetime.now(timezone.utc),
    )
    session.add(ws)
    await session.commit()
    await session.refresh(ws)
    return ws.id


@pytest.mark.asyncio
async def test_promote_success(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)
    await _create_risk_config(session)
    await _create_wallet(session)

    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "live"
    assert data["id"] == str(var_id)


@pytest.mark.asyncio
async def test_promote_wrong_status(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    var_id = await _create_variation(session, exp_id, StrategyStatus.BACKTESTED)
    await _create_risk_config(session)
    await _create_wallet(session)

    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 409
    assert "backtested" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promote_not_found(client: AsyncClient):
    fake_id = uuid.uuid4()
    resp = await client.post(f"/api/variations/{fake_id}/promote")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_promote_no_risk_config(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)
    await _create_wallet(session)

    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 422
    assert "risk" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promote_max_concurrent_exceeded(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    await _create_risk_config(session, max_concurrent_live=1)
    await _create_wallet(session)

    await _create_variation(session, exp_id, StrategyStatus.LIVE)

    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)
    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 422
    assert "max concurrent" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promote_insufficient_balance(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)
    await _create_risk_config(session, max_position_size_usd=10000.0)
    await _create_wallet(session, sol=1.0, usdc=0.5)

    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 422
    assert "insufficient" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promote_no_wallet(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)
    await _create_risk_config(session)

    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 422
    assert "wallet" in resp.json()["detail"].lower()
