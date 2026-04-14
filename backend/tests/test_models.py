import uuid

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models.base import Base
from backend.app.models.enums import StrategyStatus
from backend.app.models.experiment import Experiment
from backend.app.models.strategy_variation import StrategyVariation
from backend.app.models.backtest_run import BacktestRun
from backend.app.models.risk_config import RiskConfig
from backend.app.models.task_queue import TaskQueue
from backend.app.models.ohlcv_data import OHLCVData

from datetime import datetime, timezone


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


class TestModelRoundTrip:
    def test_experiment_crud(self, session):
        exp = Experiment(
            name="Test Experiment",
            description="Testing round-trip",
            max_iterations=50,
        )
        session.add(exp)
        session.commit()

        loaded = session.get(Experiment, exp.id)
        assert loaded is not None
        assert loaded.name == "Test Experiment"
        assert loaded.max_iterations == 50
        assert loaded.is_active is True

    def test_strategy_variation_with_status(self, session):
        exp = Experiment(name="Test", max_iterations=10)
        session.add(exp)
        session.flush()

        var = StrategyVariation(
            experiment_id=exp.id,
            code="def generate_signal(df): return df['close'] > df['close'].shift(1)",
            status=StrategyStatus.GENERATED,
        )
        session.add(var)
        session.commit()

        loaded = session.get(StrategyVariation, var.id)
        assert loaded.status == StrategyStatus.GENERATED
        assert loaded.experiment_id == exp.id

    def test_strategy_variation_lineage(self, session):
        exp = Experiment(name="Test", max_iterations=10)
        session.add(exp)
        session.flush()

        parent = StrategyVariation(
            experiment_id=exp.id,
            code="parent code",
            generation=0,
        )
        session.add(parent)
        session.flush()

        child = StrategyVariation(
            experiment_id=exp.id,
            parent_id=parent.id,
            code="child code",
            generation=1,
        )
        session.add(child)
        session.commit()

        loaded_child = session.get(StrategyVariation, child.id)
        assert loaded_child.parent_id == parent.id

    def test_status_transition_valid(self, session):
        exp = Experiment(name="Test", max_iterations=10)
        session.add(exp)
        session.flush()

        var = StrategyVariation(
            experiment_id=exp.id,
            code="code",
            status=StrategyStatus.GENERATED,
        )
        session.add(var)
        session.flush()

        var.transition_to(StrategyStatus.BACKTESTING)
        assert var.status == StrategyStatus.BACKTESTING

        var.transition_to(StrategyStatus.BACKTESTED)
        assert var.status == StrategyStatus.BACKTESTED

    def test_status_transition_invalid(self, session):
        exp = Experiment(name="Test", max_iterations=10)
        session.add(exp)
        session.flush()

        var = StrategyVariation(
            experiment_id=exp.id,
            code="code",
            status=StrategyStatus.GENERATED,
        )
        session.add(var)
        session.flush()

        with pytest.raises(ValueError, match="Invalid transition"):
            var.transition_to(StrategyStatus.LIVE)

    def test_backtest_run_linked_to_variation(self, session):
        exp = Experiment(name="Test", max_iterations=10)
        session.add(exp)
        session.flush()

        var = StrategyVariation(
            experiment_id=exp.id, code="code"
        )
        session.add(var)
        session.flush()

        now = datetime.now(timezone.utc)
        run = BacktestRun(
            variation_id=var.id,
            start_date=now,
            end_date=now,
            sortino_ratio=2.1,
            max_drawdown=0.05,
            total_return=0.15,
        )
        session.add(run)
        session.commit()

        loaded = session.get(BacktestRun, run.id)
        assert loaded.sortino_ratio == 2.1
        assert loaded.variation_id == var.id

    def test_risk_config_round_trip(self, session):
        config = RiskConfig(
            label="global",
            max_position_size_usd=1000.0,
            max_drawdown_pct=0.1,
            max_daily_loss_usd=500.0,
            portfolio_stop_loss_pct=0.05,
            per_strategy_stop_loss_pct=0.03,
        )
        session.add(config)
        session.commit()

        loaded = session.get(RiskConfig, config.id)
        assert loaded.max_position_size_usd == 1000.0
        assert loaded.label == "global"

    def test_task_queue_round_trip(self, session):
        task = TaskQueue(
            task_type="backtest",
            payload={"variation_id": str(uuid.uuid4())},
        )
        session.add(task)
        session.commit()

        loaded = session.get(TaskQueue, task.id)
        assert loaded.task_type == "backtest"
        assert loaded.retry_count == 0
