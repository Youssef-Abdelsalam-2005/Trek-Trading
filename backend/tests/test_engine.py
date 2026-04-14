"""Tests for the execution engine lifecycle manager.

Requires a running Postgres instance. Set TEST_DATABASE_URL env var.
Default: postgresql://postgres:postgres@localhost:5432/trek_test
"""

import asyncio
import json
import os
import uuid
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import asyncpg
import pytest
import pytest_asyncio

TEST_DSN = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql://postgres:postgres@localhost:5432/trek_test",
)

SETUP_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS risk_config (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    label VARCHAR(64) NOT NULL DEFAULT 'global',
    is_active BOOLEAN NOT NULL DEFAULT true,
    max_position_size_usd FLOAT NOT NULL DEFAULT 1000,
    max_drawdown_pct FLOAT NOT NULL DEFAULT 0.25,
    max_daily_loss_usd FLOAT NOT NULL DEFAULT 500,
    max_concurrent_live INTEGER NOT NULL DEFAULT 3,
    portfolio_stop_loss_pct FLOAT NOT NULL DEFAULT 0.25,
    per_strategy_stop_loss_pct FLOAT NOT NULL DEFAULT 0.15,
    paper_trading_duration_hours INTEGER NOT NULL DEFAULT 72,
    min_sortino_threshold FLOAT NOT NULL DEFAULT 1.5,
    max_max_drawdown_pct FLOAT NOT NULL DEFAULT 0.15,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS experiment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name VARCHAR(255) NOT NULL DEFAULT 'test',
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS strategy_variation (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    experiment_id UUID NOT NULL REFERENCES experiment(id) ON DELETE CASCADE,
    parent_id UUID REFERENCES strategy_variation(id) ON DELETE SET NULL,
    name VARCHAR(255),
    status VARCHAR(32) NOT NULL DEFAULT 'generated',
    code TEXT NOT NULL DEFAULT '',
    generation INTEGER NOT NULL DEFAULT 0,
    llm_input_tokens INTEGER NOT NULL DEFAULT 0,
    llm_output_tokens INTEGER NOT NULL DEFAULT 0,
    llm_cost_usd FLOAT NOT NULL DEFAULT 0.0,
    cumulative_llm_cost_usd FLOAT NOT NULL DEFAULT 0.0,
    error_message TEXT,
    metadata JSON,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS live_deployment (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    variation_id UUID NOT NULL REFERENCES strategy_variation(id) ON DELETE CASCADE,
    started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    stopped_at TIMESTAMPTZ,
    stop_reason VARCHAR(64),
    total_pnl_usd FLOAT,
    total_pnl_sol FLOAT,
    max_drawdown FLOAT,
    trade_count INTEGER,
    metrics JSON,
    last_signal_at TIMESTAMPTZ,
    decision_interval_seconds INTEGER NOT NULL DEFAULT 300,
    peak_equity_usd FLOAT,
    peak_equity_sol FLOAT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS trade (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    variation_id UUID NOT NULL REFERENCES strategy_variation(id) ON DELETE CASCADE,
    source VARCHAR(16) NOT NULL DEFAULT 'live',
    direction VARCHAR(8) NOT NULL,
    pair VARCHAR(32) NOT NULL DEFAULT 'SOL/USDC',
    price FLOAT NOT NULL,
    quantity FLOAT NOT NULL,
    value_usd FLOAT NOT NULL,
    fee_usd FLOAT,
    slippage_bps FLOAT,
    tx_signature VARCHAR(128),
    executed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    metadata JSON,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
"""

TEARDOWN_SQL = """
DROP TABLE IF EXISTS trade CASCADE;
DROP TABLE IF EXISTS live_deployment CASCADE;
DROP TABLE IF EXISTS strategy_variation CASCADE;
DROP TABLE IF EXISTS experiment CASCADE;
DROP TABLE IF EXISTS risk_config CASCADE;
"""


@pytest_asyncio.fixture
async def pool():
    p = await asyncpg.create_pool(TEST_DSN, min_size=2, max_size=5)
    async with p.acquire() as conn:
        await conn.execute(TEARDOWN_SQL)
        await conn.execute(SETUP_TABLES_SQL)
    yield p
    async with p.acquire() as conn:
        await conn.execute(TEARDOWN_SQL)
    await p.close()


@pytest_asyncio.fixture
async def seed_data(pool):
    """Create an experiment, a live strategy, and an active deployment."""
    exp_id = uuid.uuid4()
    var_id = uuid.uuid4()
    dep_id = uuid.uuid4()

    async with pool.acquire() as conn:
        await conn.execute(
            "INSERT INTO experiment (id, name) VALUES ($1, $2)", exp_id, "test-exp"
        )
        await conn.execute(
            """INSERT INTO strategy_variation (id, experiment_id, status, code)
               VALUES ($1, $2, 'live', 'def generate_signal(data): return "hold"')""",
            var_id, exp_id,
        )
        await conn.execute(
            """INSERT INTO live_deployment (id, variation_id, started_at, decision_interval_seconds)
               VALUES ($1, $2, now(), 1)""",
            dep_id, var_id,
        )
        await conn.execute(
            """INSERT INTO risk_config (per_strategy_stop_loss_pct, max_position_size_usd,
               max_drawdown_pct, max_daily_loss_usd, portfolio_stop_loss_pct)
               VALUES (0.15, 1000, 0.25, 500, 0.25)"""
        )

    return {"experiment_id": exp_id, "variation_id": var_id, "deployment_id": dep_id}


@pytest.mark.asyncio
async def test_advisory_lock_prevents_second_engine(pool):
    """Only one engine instance can hold the advisory lock."""
    from trek.engine import ADVISORY_LOCK_ID

    async with pool.acquire() as conn1:
        locked1 = await conn1.fetchval(
            "SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_ID
        )
        assert locked1 is True

        async with pool.acquire() as conn2:
            locked2 = await conn2.fetchval(
                "SELECT pg_try_advisory_lock($1)", ADVISORY_LOCK_ID
            )
            assert locked2 is False

        await conn1.execute(
            "SELECT pg_advisory_unlock($1)", ADVISORY_LOCK_ID
        )


@pytest.mark.asyncio
async def test_load_live_deployments(pool, seed_data):
    """Engine loads active live deployments on startup."""
    from trek.engine import ExecutionEngine

    engine = ExecutionEngine(pool, TEST_DSN)
    await engine._load_risk_config()
    await engine._load_and_start_deployments()

    assert len(engine._loops) == 1
    dep_id = seed_data["deployment_id"]
    assert dep_id in engine._loops
    sl = engine._loops[dep_id]
    assert sl.variation_id == seed_data["variation_id"]
    assert sl.decision_interval_seconds == 1

    engine._stop.set()
    await engine.stop()


@pytest.mark.asyncio
async def test_stopped_deployments_not_loaded(pool, seed_data):
    """Deployments with stopped_at set are not loaded."""
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE live_deployment SET stopped_at = now() WHERE id = $1",
            seed_data["deployment_id"],
        )

    from trek.engine import ExecutionEngine

    engine = ExecutionEngine(pool, TEST_DSN)
    await engine._load_and_start_deployments()
    assert len(engine._loops) == 0
    engine._stop.set()


@pytest.mark.asyncio
async def test_signal_hold_updates_last_signal_at(pool, seed_data):
    """When generate_signal raises NotImplementedError (stub), last_signal_at is updated."""
    from trek.engine import ExecutionEngine, StrategyLoop

    engine = ExecutionEngine(pool, TEST_DSN)

    sl = StrategyLoop(
        deployment_id=seed_data["deployment_id"],
        variation_id=seed_data["variation_id"],
        strategy_code="stub",
        decision_interval_seconds=1,
        last_signal_at=None,
    )

    await engine._execute_interval(sl)
    assert sl.last_signal_at is not None

    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT last_signal_at FROM live_deployment WHERE id = $1",
            seed_data["deployment_id"],
        )
    assert row["last_signal_at"] is not None


@pytest.mark.asyncio
async def test_trade_execution_and_pnl_tracking(pool, seed_data):
    """When signal is BUY and trade executes, trade is logged and PnL updated atomically."""
    from trek.engine import ExecutionEngine, StrategyLoop, Signal, TradeResult

    engine = ExecutionEngine(pool, TEST_DSN)

    mock_signal = Signal(direction="buy", quantity=1.0, pair="SOL/USDC")
    mock_result = TradeResult(
        direction="buy",
        pair="SOL/USDC",
        price=150.0,
        quantity=1.0,
        value_usd=150.0,
        fee_usd=0.50,
        slippage_bps=5.0,
        tx_signature="abc123signature",
        executed_at=datetime.now(timezone.utc),
    )

    sl = StrategyLoop(
        deployment_id=seed_data["deployment_id"],
        variation_id=seed_data["variation_id"],
        strategy_code="stub",
        decision_interval_seconds=1,
        last_signal_at=None,
    )

    with patch("trek.engine.generate_signal", new_callable=AsyncMock, return_value=mock_signal), \
         patch("trek.engine.execute_trade", new_callable=AsyncMock, return_value=mock_result):
        await engine._execute_interval(sl)

    assert sl.last_signal_at is not None

    async with pool.acquire() as conn:
        trade = await conn.fetchrow(
            "SELECT * FROM trade WHERE variation_id = $1", seed_data["variation_id"]
        )
        assert trade is not None
        assert trade["direction"] == "buy"
        assert trade["price"] == 150.0
        assert trade["tx_signature"] == "abc123signature"
        assert trade["source"] == "live"

        dep = await conn.fetchrow(
            "SELECT * FROM live_deployment WHERE id = $1", seed_data["deployment_id"]
        )
        assert dep["total_pnl_usd"] == -150.0  # buy = negative PnL
        assert dep["trade_count"] == 1


@pytest.mark.asyncio
async def test_drawdown_halts_strategy(pool, seed_data):
    """When drawdown exceeds threshold, strategy is halted and deployment stopped."""
    from trek.engine import ExecutionEngine, StrategyLoop

    engine = ExecutionEngine(pool, TEST_DSN)
    engine._drawdown_threshold = 0.15

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE live_deployment
               SET total_pnl_usd = 50, peak_equity_usd = 100
               WHERE id = $1""",
            seed_data["deployment_id"],
        )

    sl = StrategyLoop(
        deployment_id=seed_data["deployment_id"],
        variation_id=seed_data["variation_id"],
        strategy_code="stub",
        decision_interval_seconds=1,
        last_signal_at=None,
    )
    engine._loops[seed_data["deployment_id"]] = sl

    await engine._check_drawdown(sl)

    async with pool.acquire() as conn:
        var = await conn.fetchrow(
            "SELECT status FROM strategy_variation WHERE id = $1",
            seed_data["variation_id"],
        )
        assert var["status"] == "halted"

        dep = await conn.fetchrow(
            "SELECT stopped_at, stop_reason FROM live_deployment WHERE id = $1",
            seed_data["deployment_id"],
        )
        assert dep["stopped_at"] is not None
        assert dep["stop_reason"] == "drawdown_exceeded"

    assert seed_data["deployment_id"] not in engine._loops


@pytest.mark.asyncio
async def test_drawdown_within_threshold_does_not_halt(pool, seed_data):
    """When drawdown is within threshold, strategy continues."""
    from trek.engine import ExecutionEngine, StrategyLoop

    engine = ExecutionEngine(pool, TEST_DSN)
    engine._drawdown_threshold = 0.15

    async with pool.acquire() as conn:
        await conn.execute(
            """UPDATE live_deployment
               SET total_pnl_usd = 90, peak_equity_usd = 100
               WHERE id = $1""",
            seed_data["deployment_id"],
        )

    sl = StrategyLoop(
        deployment_id=seed_data["deployment_id"],
        variation_id=seed_data["variation_id"],
        strategy_code="stub",
        decision_interval_seconds=1,
        last_signal_at=None,
    )
    engine._loops[seed_data["deployment_id"]] = sl

    await engine._check_drawdown(sl)

    async with pool.acquire() as conn:
        var = await conn.fetchrow(
            "SELECT status FROM strategy_variation WHERE id = $1",
            seed_data["variation_id"],
        )
        assert var["status"] == "live"

    assert seed_data["deployment_id"] in engine._loops


@pytest.mark.asyncio
async def test_kill_switch_stops_all_strategies(pool, seed_data):
    """Kill switch kills all live strategies and stops all deployments."""
    from trek.engine import ExecutionEngine, StrategyLoop

    engine = ExecutionEngine(pool, TEST_DSN)

    sl = StrategyLoop(
        deployment_id=seed_data["deployment_id"],
        variation_id=seed_data["variation_id"],
        strategy_code="stub",
        decision_interval_seconds=1,
        last_signal_at=None,
    )
    engine._loops[seed_data["deployment_id"]] = sl

    await engine._handle_kill_switch()

    assert len(engine._loops) == 0

    async with pool.acquire() as conn:
        var = await conn.fetchrow(
            "SELECT status FROM strategy_variation WHERE id = $1",
            seed_data["variation_id"],
        )
        assert var["status"] == "killed"

        dep = await conn.fetchrow(
            "SELECT stopped_at, stop_reason FROM live_deployment WHERE id = $1",
            seed_data["deployment_id"],
        )
        assert dep["stopped_at"] is not None
        assert dep["stop_reason"] == "kill_switch"


@pytest.mark.asyncio
async def test_restart_idempotency(pool, seed_data):
    """After restart, engine does not re-execute a recently completed interval."""
    from trek.engine import ExecutionEngine

    recent = datetime.now(timezone.utc) - timedelta(seconds=10)
    async with pool.acquire() as conn:
        await conn.execute(
            "UPDATE live_deployment SET last_signal_at = $1, decision_interval_seconds = 300 WHERE id = $2",
            recent, seed_data["deployment_id"],
        )

    engine = ExecutionEngine(pool, TEST_DSN)
    await engine._load_and_start_deployments()

    assert len(engine._loops) == 1
    sl = list(engine._loops.values())[0]
    assert sl.last_signal_at == recent

    engine._stop.set()
    await engine.stop()
