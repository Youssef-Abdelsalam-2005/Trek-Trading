from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from backend.app.models.base import Base
from backend.app.models.enums import StrategyStatus
from backend.app.models.experiment import Experiment
from backend.app.models.risk_config import RiskConfig
from backend.app.models.strategy_variation import StrategyVariation
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
        experiment_id=None,
        per_strategy_drawdown_halt=15.0,
        max_concurrent_live=3,
    )
    defaults.update(overrides)
    rc = RiskConfig(**defaults)
    session.add(rc)
    await session.commit()
    await session.refresh(rc)
    return rc.id


@pytest.mark.asyncio
async def test_promote_success(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)
    await _create_risk_config(session)

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

    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 409
    assert "backtested" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_promote_not_found(client: AsyncClient):
    fake_id = uuid.uuid4()
    resp = await client.post(f"/api/variations/{fake_id}/promote")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_promote_no_risk_config_falls_back_to_defaults(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)

    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 200
    assert resp.json()["status"] == "live"


@pytest.mark.asyncio
async def test_promote_max_concurrent_exceeded(client: AsyncClient, session: AsyncSession):
    exp_id = await _create_experiment(session)
    await _create_risk_config(session, max_concurrent_live=1)

    await _create_variation(session, exp_id, StrategyStatus.LIVE)

    var_id = await _create_variation(session, exp_id, StrategyStatus.PAPER_PASSED)
    resp = await client.post(f"/api/variations/{var_id}/promote")
    assert resp.status_code == 422
    assert "max concurrent" in resp.json()["detail"].lower()
