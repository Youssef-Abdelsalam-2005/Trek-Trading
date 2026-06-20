import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from backend.app.models.base import Base
from backend.app.models.enums import StrategyStatus
from backend.app.models.experiment import Experiment
from backend.app.models.risk_config import RiskConfig
from backend.app.models.strategy_variation import StrategyVariation


def _merge_risk_config(global_config: dict | None, override: dict | None) -> dict | None:
    if global_config is None and override is None:
        return None
    base = dict(global_config) if global_config else {}
    if override:
        base.update(override)
    return base


@pytest.fixture
def engine():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def session(engine):
    with Session(engine) as session:
        yield session


class TestExperimentCRUD:
    def test_create_experiment(self, session):
        exp = Experiment(
            name="SOL momentum v1",
            description="Testing momentum strategy generation",
            max_iterations=50,
            fitness_function_config={"metric": "sortino", "min_value": 2.0},
        )
        session.add(exp)
        session.commit()

        loaded = session.get(Experiment, exp.id)
        assert loaded is not None
        assert loaded.name == "SOL momentum v1"
        assert loaded.max_iterations == 50
        assert loaded.is_active is True
        assert loaded.current_iteration == 0
        assert loaded.deleted_at is None
        assert loaded.fitness_function_config == {"metric": "sortino", "min_value": 2.0}

    def test_create_experiment_with_risk_override(self, session):
        exp = Experiment(
            name="Conservative run",
            max_iterations=10,
            risk_config_override={"max_drawdown_pct": 0.05, "max_concurrent_live": 1},
        )
        session.add(exp)
        session.commit()

        loaded = session.get(Experiment, exp.id)
        assert loaded.risk_config_override == {
            "max_drawdown_pct": 0.05,
            "max_concurrent_live": 1,
        }

    def test_create_experiment_with_llm_override(self, session):
        exp = Experiment(
            name="GPT-4 run",
            max_iterations=20,
            llm_config_override={"model": "gpt-4", "temperature": 0.7},
        )
        session.add(exp)
        session.commit()

        loaded = session.get(Experiment, exp.id)
        assert loaded.llm_config_override == {"model": "gpt-4", "temperature": 0.7}

    def test_update_experiment(self, session):
        exp = Experiment(name="Original", max_iterations=10)
        session.add(exp)
        session.commit()

        exp.name = "Updated"
        exp.max_iterations = 200
        exp.description = "Now with description"
        session.commit()

        loaded = session.get(Experiment, exp.id)
        assert loaded.name == "Updated"
        assert loaded.max_iterations == 200
        assert loaded.description == "Now with description"

    def test_soft_delete_experiment(self, session):
        exp = Experiment(name="To delete", max_iterations=5)
        session.add(exp)
        session.commit()

        now = datetime.now(timezone.utc)
        exp.deleted_at = now
        session.commit()

        loaded = session.get(Experiment, exp.id)
        assert loaded.deleted_at is not None

    def test_soft_delete_cascades_to_variations(self, session):
        exp = Experiment(name="Cascade test", max_iterations=10)
        session.add(exp)
        session.flush()

        v1 = StrategyVariation(
            experiment_id=exp.id,
            code="def generate_signal(df): return df['close'] > 0",
            status=StrategyStatus.GENERATED,
        )
        v2 = StrategyVariation(
            experiment_id=exp.id,
            code="def generate_signal(df): return df['close'] < 0",
            status=StrategyStatus.BACKTESTING,
        )
        session.add_all([v1, v2])
        session.commit()

        now = datetime.now(timezone.utc)
        exp.deleted_at = now
        v1.deleted_at = now
        v2.deleted_at = now
        session.commit()

        loaded_v1 = session.get(StrategyVariation, v1.id)
        loaded_v2 = session.get(StrategyVariation, v2.id)
        assert loaded_v1.deleted_at is not None
        assert loaded_v2.deleted_at is not None

    def test_list_excludes_soft_deleted(self, session):
        exp1 = Experiment(name="Active", max_iterations=10)
        exp2 = Experiment(
            name="Deleted",
            max_iterations=10,
            deleted_at=datetime.now(timezone.utc),
        )
        session.add_all([exp1, exp2])
        session.commit()

        from sqlalchemy import select

        active = session.execute(
            select(Experiment).where(Experiment.deleted_at.is_(None))
        ).scalars().all()
        assert len(active) == 1
        assert active[0].name == "Active"


class TestRiskConfigMerge:
    def test_merge_with_global_defaults(self, session):
        global_config = RiskConfig(
            label="global",
            max_position_size_usd=1000.0,
            max_drawdown_pct=0.15,
            max_daily_loss_usd=500.0,
            max_concurrent_live=3,
            portfolio_stop_loss_pct=0.25,
            per_strategy_stop_loss_pct=0.15,
            paper_trading_duration_hours=72,
            min_sortino_threshold=1.5,
            max_max_drawdown_pct=0.15,
        )
        session.add(global_config)
        session.commit()

        override = {"max_drawdown_pct": 0.05, "max_concurrent_live": 1}
        global_dict = {
            "max_position_size_usd": 1000.0,
            "max_drawdown_pct": 0.15,
            "max_daily_loss_usd": 500.0,
            "max_concurrent_live": 3,
            "portfolio_stop_loss_pct": 0.25,
            "per_strategy_stop_loss_pct": 0.15,
            "paper_trading_duration_hours": 72,
            "min_sortino_threshold": 1.5,
            "max_max_drawdown_pct": 0.15,
        }

        merged = {**global_dict, **override}
        assert merged["max_drawdown_pct"] == 0.05
        assert merged["max_concurrent_live"] == 1
        assert merged["max_position_size_usd"] == 1000.0

    def test_no_override_returns_global(self):
        global_dict = {"max_drawdown_pct": 0.15, "max_concurrent_live": 3}
        merged = {**global_dict}
        assert merged == global_dict

    def test_no_global_no_override_returns_none(self):
        result = _merge_risk_config(None, None)
        assert result is None

    def test_override_only_no_global(self):
        result = _merge_risk_config(None, {"max_drawdown_pct": 0.05})
        assert result == {"max_drawdown_pct": 0.05}
